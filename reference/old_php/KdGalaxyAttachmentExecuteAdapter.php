<?php

namespace Adapter\KdGalaxy;

use Domain\Datahub\Instance\Storage\DataStatus;
use Domain\Datahub\Instance\Storage\LogStatus;

class KdGalaxyAttachmentExecuteAdapter extends KdGalaxyExecuteAdapter
{
    public function generateRequestParams($data = null)
    {
        if ($data != null) {
            $this->Collation->setData($data);
        }
        $request = $this->Collation->run($this->metaData['request']);
        $other = $this->Collation->run($this->metaData['otherRequest']);
        $otherResponse = $this->Collation->run($this->metaData['otherResponse']);
        $attachmentEnabled = (bool)($otherResponse['uploadAttachment'] ?? false);
        if ($attachmentEnabled) {
            $request['uploadRequest'] = $otherResponse ?? null;
        }

        if (empty($other) || $other == null) {
            return $request;
        }

        $key = $other['key'];
        return [$key => [$request]];
    }
    public function handleResponse($response, $jobId = null)
    {
        if (!isset($response['errorCode'])) {
            return $this->handleError($response, $jobId);
        }
        if ($response['errorCode'] != 0) {
            return $this->handleError($response, $jobId);
        }
        if (isset($response['data'])) {
            if (isset($response['data']['errorInfo'])) {
                if ($response['data']['success'] == false) {
                    return $this->handleError($response, $jobId);
                }
            }
        }
        // 验证是否下载附件
        $invokeRequest = $this->invokeRequest ?? [];
        $invokeRequest = json_decode(json_encode($invokeRequest), true);
        $invokeuploadRequest = isset($invokeRequest['data'][0]) ? $invokeRequest['data'][0] : null;

        if (isset($invokeuploadRequest['uploadRequest'])) {
            // 生成单据之后，上传附件
            $uploadRequest = $invokeuploadRequest['uploadRequest'] ?? null;
            $UploadAttachment = (bool)($uploadRequest['uploadAttachment'] ?? false);
            if ($UploadAttachment) {
                $this->uploadfile($uploadRequest, $uploadRequest['uploadapi'], $response);
            }
            $this->getAsynTargetJobStorage()->updateResponse($jobId, DataStatus::FINISHED, $response, [], null, $this->active);
        } else {
            // 没有下载附件配置，直接设为完成
            $this->getAsynTargetJobStorage()->updateResponse($jobId, DataStatus::FINISHED, $response, [], null, $this->active);
        }

        $this->handleSuccessCallback($response, $jobId);
        if (isset($this->metaData['autoCheck'])) {
            $this->_autoCheck($response);
        }
        return $response;
    }
    public function uploadfile($request, $uploadapi, $response)
    {
        $this->getLogStorage()->insertOne(['text' => '附件上传接口调用失败', 'request' => $request]);
        $uploadRequest = $request['upload'] ?? null;
        if ($uploadRequest === null) {
            return false;
        }

        // 如果不是数组，转换为数组统一处理
        if (!is_array($uploadRequest) || !isset($uploadRequest[0])) {
            $uploadRequest = [$uploadRequest];
        }
        $results = [];
        foreach ($uploadRequest as $key => $val) {
            $newrequest = [];
            $billNo = null;
            $billNo = $this->getValueByPath($response, $val['billNo']);
            if ($billNo === null) {
                $this->getLogStorage()->insertOne(['text' => '附件上传失败，未找到单据编号', 'request' => $request], LogStatus::ERROR);
                continue;
            }
            // 设置billNo
            $val['billNo'] = $billNo;

            // 准备上传参数
            $newrequest['file'] = $val['file'] ?? null;
            unset($val['file']);
            $newrequest['parameter'] = $val;
            $this->getLogStorage()->insertOne(['text' => '上传附件参数' . $key, 'request' => $newrequest]);

            try {
                $result = $this->SDK->uploadFile($uploadapi, $newrequest, 'POST');
                $results[] = $result;
                // 检查上传是否成功，假设失败时返回false或 errorCode 不为 200 或 status 不为 true
                if (isset($result['status']) && $result['status'] != true) {
                    $this->getLogStorage()->insertOne(['text' => '附件上传接口调用失败', 'request' => $newrequest, 'response' => $result], LogStatus::ERROR);
                }
            } catch (\Exception $e) {
                $this->getLogStorage()->insertOne([
                    'text' => '附件上传接口调用异常: ' . $e->getMessage(),
                    'request' => $newrequest,
                    'exception' => $e
                ], LogStatus::ERROR);
                $results[] = false;
            }
        }

        return count($results) === 1 ? $results[0] : $results;
    }
    function getValueByPath($array, $path)
    {
        // 如果路径不包含点号，直接返回原值（不尝试从数组/对象取值）
        if (strpos($path, '.') === false) {
            return $path;
        }

        // 否则按多级路径解析
        $keys = explode('.', $path);
        $current = $array;

        foreach ($keys as $key) {
            if (is_array($current) && array_key_exists($key, $current)) {
                $current = $current[$key];
            } elseif (is_object($current) && property_exists($current, $key)) {
                $current = $current->$key;
            } else {
                return null; // 路径不存在返回 null
            }
        }

        return $current;
    }
}
