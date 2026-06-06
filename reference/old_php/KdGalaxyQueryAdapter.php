<?php

namespace Adapter\KdGalaxy;

use Domain\Datahub\Connector\ConnectorRepository;
use Domain\Datahub\Instance\Adapter\Adapter;
use Adapter\KdGalaxy\SDK\KdGalaxySDK;
use Adapter\KdGalaxy\Throwable\KdGalaxyThrowable;
use Domain\Datahub\Instance\LogMessage;
use Domain\Datahub\Instance\Storage\LogStatus;
use Domain\Datahub\Instance\Storage\DataStatus;

class KdGalaxyQueryAdapter extends Adapter
{
    const DIRECTION = 'source';

    public $model = null;

    public function dispatch()
    {
        $this->_setVariable();
        $request = $this->generateRequestParams();
        $jobs = [];
        $jobs[] = $request;
        $jobId = $this->getAsynSourceJobStorage()->insertOne($this->metaData['api'], $request);
        $this->asynSourceJob(0, $jobId);
        $this->getLogStorage()->insertOne(['text' => sprintf(LogMessage::DISPATCH_SOURCE_FINISH, count($jobs))], LogStatus::SUCCESS);
        return ['status' => true, 'content' => $jobs];
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
        if(empty($list)){
            $this->getAsynSourceJobStorage()->updateResponse($jobId, DataStatus::FINISHED, $response, 0, $this->active);
            return;
        }
        $operation = null;
        if (isset($this->metaData['operation'])) {
            $operation = $this->metaData['operation'];
        }
        $inserted = 0;
        $idCheck = true;
        if (isset($this->metaData['idCheck'])) {
            $idCheck = $this->metaData['idCheck'];
        }
        if (!empty($list)) {
            unset($response['rows']);
            foreach ($list as $obj) {
                if ($operation === null) {
                    $id = $this->getDataKeyValue($obj, $this->metaData['id']) . '';
                    $number = $this->getDataKeyValue($obj, $this->metaData['number'] . '');
                    $result = $this->getDataStorage()->insertOne($id, $number, $obj, $idCheck);
                    $inserted++;
                } else if ($operation['method'] === 'splitArray') {
                    $data = $this->splitArray($obj, $operation['arrayKey']);
                    foreach ($data as $d) {
                        $id = $this->getDataKeyValue($d, $this->metaData['id']) . '';
                        $number = $this->getDataKeyValue($d, $this->metaData['number'] . '');
                        $result = $this->getDataStorage()->insertOne($id, $number, $d, $idCheck, $jobId, $jobId);
                        $inserted++;
                    }
                }
            }
        }
        $this->getAsynSourceJobStorage()->updateResponse($jobId, DataStatus::FINISHED, $response, $inserted, $this->active);
        if (count($list) > 0 && isset($this->invokeRequest['pageNo'])) {
            $request = $this->invokeRequest;
            $request['pageNo'] += 1;
            $jobId = $this->getAsynSourceJobStorage()->insertOne($this->metaData['api'], $request);
            $this->asynSourceJob(5, $jobId);
        }
        return $response;
    }

    public function handleError($response, $jobId = null)
    {
        $throw = new KdGalaxyThrowable($this);
        $throw->handle($jobId, $response);
        $this->getAsynSourceJobStorage()->updateResponse($jobId, DataStatus::ERROR, $response, 0, $this->active);
        $this->getLogStorage()->insertOne(['text' => LogMessage::INVOKE_FAIL, 'response' => $response], LogStatus::ERROR);
        return $response;
    }

    public function connect()
    {
        if ($this->SDK != null) {
            return $this->SDK;
        }
        $connector = ConnectorRepository::findOne($this->strategy[$this->direction]->connector_id);
        $env = 'env_' . $connector->env . '_params';
        $this->SDK = new KdGalaxySDK($connector->id, $connector->$env, $connector->env);
        $conn = $this->SDK->connection();
        return $conn;
    }
}