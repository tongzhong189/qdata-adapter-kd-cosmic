<?php

namespace Adapter\KdGalaxy;

use Domain\Datahub\Instance\Storage\LogStatus;
use Domain\Datahub\Instance\Storage\DataStatus;

class KdGalaxyAttachmentQueryAdapter extends KdGalaxyQueryAdapter
{
    public function invoke($request)
    {
        $this->invokeRequest = $request;
        return $this->SDK->invoke(
            $this->currentJob->api,
            $request,
            $this->metaData['method']
        );
    }

    public function handleResponse($response, $jobId = null)
    {
        if (!isset($response['errorCode'])) {
            return $this->handleError($response, $jobId);
        }
        if ($response['errorCode'] != 0) {
            return $this->handleError($response, $jobId);
        }

        $response = $response['data'] ?? [];
        $list = $response['rows'] ?? [];
        $inserted = 0;
        $idCheck = $this->metaData['idCheck'];
        $otherResponse = $this->Collation->run($this->metaData['otherResponse']);
        $attachmentEnabled = (bool)($otherResponse['DownloadAttachment'] ?? false);

        try {
            $allfileinfo = [];
            foreach ($list as $arr) {
                $id = $this->getDataKeyValue($arr, $this->metaData['id']) . '';
                $number = $this->getDataKeyValue($arr, $this->metaData['number'] . '');

                $attachments = [];
                if ($attachmentEnabled) {
                    $downloadRequest = $otherResponse['downloadRequest'] ?? null;
                    $downloadapi = $otherResponse['downloadapi'] ?? null;

                    if ($downloadRequest && $downloadapi) {
                        $downloadRequest['billNo'] = $arr[$downloadRequest['billNo']] ?? null;
                        $newrequest = ['parameter' => $downloadRequest];
                        
                        $fileInfo = $this->downloadfile($newrequest, $downloadapi);

                        if ($fileInfo === false) {
                            $this->getLogStorage()->insertOne(
                                ['text' => '附件下载失败，数据仍然保存', 'id' => $id],
                                LogStatus::ERROR
                            );
                        } else {
                            $attachments = $fileInfo;
                            $allfileinfo[] = $fileInfo;
                        }
                    }
                }

                // 无论是否有附件，都保存数据
                $arr['attachments'] = $attachments;
                $this->getDataStorage()->insertOne($id, $number, $arr, $idCheck, $jobId);
                $inserted++;
            }

            if (!empty($allfileinfo)) {
                //把附件放到源数据中
                $this->getLogStorage()->insertOne(
                    ['text' => '部分附件下载成功', 'fileInfo' => $allfileinfo],
                    LogStatus::SUCCESS
                );
            }
        } catch (\Throwable $e) {
            $this->getLogStorage()->insertOne(
                ['text' => '响应数据处理失败', 'error' => $e->getMessage()],
                LogStatus::ERROR
            );
            $this->getAsynSourceJobStorage()->updateResponse($jobId, DataStatus::ERROR, [], 0, $this->active);
            return ['status' => false, 'error' => $e->getMessage()];
        }

        $this->getAsynSourceJobStorage()->updateResponse(
            $jobId,
            DataStatus::FINISHED,
            [],
            $inserted,
            $this->active
        );
        return true;
    }


    public function downloadfile($request, $downloadapi)
    {
        // 调用接口获取附件信息
        $result = $this->SDK->invoke($downloadapi, $request, $method = 'POST');

        if (isset($result['status']) && $result['status'] === false) {
            $this->getLogStorage()->insertOne([
                'text' => '附件下载接口调用失败',
                'response' => $result
            ], LogStatus::ERROR);
            return false;
        }

        // 检查是否有有效的数据
        if (empty($result['data']) || !is_array($result['data'])) {
            $this->getLogStorage()->insertOne([
                'text' => '没有可下载的附件',
                'response' => $result
            ], LogStatus::ERROR);
            return false;
        }

        $basePath = public_path("k3cloud/" . date('Y-m'));
        $directory = "k3cloud/" . date('Y-m');

        if (!is_dir($basePath)) {
            mkdir($basePath, 0777, true);
        }

        $downloadedFiles = [];

        foreach ($result['data'] as $fileItem) {
            // 跳过无效的文件项
            if (empty($fileItem['url']) || empty($fileItem['name'])) {
                $this->getLogStorage()->insertOne([
                    'text' => '跳过无效文件项',
                    'fileItem' => $fileItem
                ], LogStatus::WARNING);
                continue;
            }

            $originalName = pathinfo($fileItem['name'], PATHINFO_FILENAME);
            $extension = pathinfo($fileItem['name'], PATHINFO_EXTENSION);

            // 生成安全的文件名
            $safeName = preg_replace('/[^a-zA-Z0-9\-_]/', '', $originalName);
            $uniqueName = $safeName . '_' . time() . '_' . mt_rand() . '.' . $extension;
            $filePath = $basePath . '/' . $uniqueName;

            try {
                // 使用cURL下载文件
                $ch = curl_init();
                curl_setopt($ch, CURLOPT_URL, $fileItem['url']);
                curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
                curl_setopt($ch, CURLOPT_FOLLOWLOCATION, true);
                curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, false);

                $fileContent = curl_exec($ch);
                $error = curl_error($ch);
                $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
                curl_close($ch);

                if ($error) {
                    throw new \Exception('cURL error: ' . $error);
                }

                if ($httpCode !== 200) {
                    throw new \Exception('HTTP request failed with code: ' . $httpCode);
                }

                // 保存文件
                if (file_put_contents($filePath, $fileContent) === false) {
                    throw new \Exception('Failed to write file to disk');
                }

                $appUrl = config('app.url', 'https://pro.qliang.cloud');
                $downloadUrl = $appUrl . '/' . $directory . '/' . $uniqueName;

                $fileInfo = [
                    'originalName' => $fileItem['name'],
                    'fileName' => $uniqueName,
                    'filePath' => $filePath,
                    'downloadUrl' => $downloadUrl,
                    'fileSize' => filesize($filePath)
                ];

                $downloadedFiles[] = $fileInfo;

                $this->getLogStorage()->insertOne([
                    'text' => '附件保存成功: ' . $fileItem['name'],
                    'fileInfo' => $fileInfo
                ], LogStatus::SUCCESS);
            } catch (\Throwable $e) {
                $this->getLogStorage()->insertOne([
                    'text' => '附件下载失败: ' . $fileItem['name'],
                    'error' => $e->getMessage(),
                    'fileItem' => $fileItem
                ], LogStatus::ERROR);
                // 继续处理下一个文件
                continue;
            }
        }

        return !empty($downloadedFiles) ? $downloadedFiles : false;
    }
}
