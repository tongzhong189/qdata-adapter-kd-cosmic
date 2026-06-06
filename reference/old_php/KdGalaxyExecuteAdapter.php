<?php

namespace Adapter\KdGalaxy;

use Adapter\KdGalaxy\SDK\KdGalaxySDK;
use Adapter\KdGalaxy\Throwable\KdGalaxyThrowable;
use Domain\Datahub\Connector\ConnectorRepository;
use Domain\Datahub\Instance\Adapter\Adapter;
use Domain\Datahub\Instance\LogMessage;
use Domain\Datahub\Instance\Storage\DataStatus;
use Domain\Datahub\Instance\Storage\LogStatus;

class KdGalaxyExecuteAdapter extends Adapter
{
    const DIRECTION = 'target';

    public $model = null;
    private $times = 0;

    public function dispatch()
    {
        $this->times++;
        if ($this->times >= 10) {
            $this->asynTargetJobDispatch(15);
            return;
        }
        $this->_setVariable();
        $operation = null;
        if (isset($this->metaData['operation'])) {
            $operation = $this->metaData['operation'];
        }
        $data = $this->getDataStorage()->fetch($operation);
        if (count($data) === 0) {
            return $this->_returnDispatch();
        }
    
        try {
            $request = $this->generateRequestParams($data);
        } catch (\Throwable $th) {
            $this->getLogStorage()->insertOne(['text' => $th->getMessage(), 'data' => $data], LogStatus::ERROR);
            $this->getDataStorage()->setFetchStatus(DataStatus::CONTINUE);
            return $this->dispatch();
        }
        $request = $this->removeParamsNull($request);

        if (!$request) {
            $this->getLogStorage()->insertOne(['text' => LogMessage::DISPATCH_TARGET_REQUEST_ERROR, 'request' => $request], LogStatus::ERROR);
            return;
        }
        $jobId = $this->getAsynTargetJobStorage()->insertOne($this->metaData['api'], $request, $this->getDataStorage()->ids, $this->getDataStorage()->dataRange);
        $this->getDataStorage()->setFetchStatus(DataStatus::QUEUE, null, null, new \MongoDB\BSON\ObjectId($jobId));
        $this->jobs[] = $jobId;
        $this->asynTargetJob(round($this->asynTimes), $jobId);
        $this->asynTimes += 1.4;
        $this->dispatch();
        return true;
    }

    public function generateRequestParams($data = null)
    {
        if ($data != null) {
            $this->Collation->setData($data);
        }
        $request = $this->Collation->run($this->metaData['request']);
        $other = $this->Collation->run($this->metaData['otherRequest']);
        if (empty($other) || $other == null) {
            return $request;
        }
        $key = $other['key'];
        return [$key => [$request]];
    }

    public function handleResponse($response, $jobId = null)
    {
        if (!isset($response['errorCode']) || !isset($response['status'])) {
            return $this->handleError($response, $jobId);
        }
        $isSuccess = ($response['status'] === true) && ($response['errorCode'] == 0 || $response['errorCode'] === '');
        if (!$isSuccess) {
            return $this->handleError($response, $jobId);
        }
        if (isset($response['data'])) {
            if (isset($response['data']['errorInfo'])) {
                if ($response['data']['success'] == false) {
                    return $this->handleError($response, $jobId);
                }
            }
        }
        $this->getAsynTargetJobStorage()->updateResponse($jobId, DataStatus::FINISHED, $response, [], null, $this->active);
        $this->handleSuccessCallback($response, $jobId);
        if (isset($this->metaData['autoCheck'])) {
            $this->_autoCheck($response);
        }
        return $response;
    }
    public function dispatchOne($id,$otherParams = [])
    {
        $this->_setVariable();
        $data = $this->getDataStorage()->findOne($id);
        $data = $data->content;
        if (!$data) {
            return ['status' => false, 'content' => '', 'jobId' => ''];
        }
        $request = null;
        try {
            $request = $this->generateRequestParams($data);
        } catch (\Throwable $th) {
            $this->getLogStorage()->insertOne(['text' => '强制关联检验检查,无法关联,标记跳过', 'data' => $th->getMessage()], LogStatus::ERROR);
            $this->getDataStorage()->setFetchStatus(DataStatus::CONTINUE);
            return;
        }
        if (!$request) {
            $this->getLogStorage()->insertOne(['text' => LogMessage::DISPATCH_TARGET_REQUEST_ERROR, 'request' => $request], LogStatus::ERROR);
            $this->getDataStorage()->setFetchStatus(DataStatus::ERROR, null, ['request' => $request]);
            return ['status' => false, 'content' => '', 'jobId' => ''];
        }
        $jobId = $this->getAsynTargetJobStorage()->insertOne($this->metaData['api'], $request, $this->getDataStorage()->ids, $this->getDataStorage()->dataRange);
        $this->getDataStorage()->setFetchStatus(DataStatus::QUEUE, null, null, new \MongoDB\BSON\ObjectId($jobId));
        return ['status' => true, 'content' => $request, 'jobId' => $jobId];
    }


    public function handleError($response, $jobId = null)
    {
        $this->getLogStorage()->insertOne(['text' => sprintf(LogMessage::EXEC_JOB_RESPONSE, $jobId->__toString()), 'response' => $response], LogStatus::RECORD);
        $throw = new KdGalaxyThrowable($this);
        $throw->handle($jobId, $response);
        $this->getAsynTargetJobStorage()->updateResponse($jobId, DataStatus::ERROR, $response, [], null, $this->active);
        $this->reQueue();
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
