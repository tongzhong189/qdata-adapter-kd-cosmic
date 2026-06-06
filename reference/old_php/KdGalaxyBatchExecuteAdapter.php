<?php


namespace Adapter\KdGalaxy;


use Adapter\KdGalaxy\SDK\KdGalaxySDK;
use Adapter\KdGalaxy\Throwable\KdGalaxyThrowable;
use Domain\Datahub\Connector\ConnectorRepository;
use Domain\Datahub\Instance\Adapter\Adapter;
use Domain\Datahub\Instance\LogMessage;
use Domain\Datahub\Instance\Storage\DataStatus;
use Domain\Datahub\Instance\Storage\LogStatus;

class KdGalaxyBatchExecuteAdapter extends Adapter
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
            //强制关联检验检查
            if ($operation === null) {
                $request = $this->generateRequestParams($data);
            } else if ($operation['method'] === 'batchArraySave') {
                if (!isset($data['array'])) {
                    $data['array'] = [$data];
                }

                if (isset($data[$operation['rowsKey']])) {
                    $request = $this->generateBatchRequestParams($data[$operation['rowsKey']]);
                } else {
                    $request = $this->generateBatchRequestParams($data);
                }
            }
        } catch (\Throwable $th) {
            $msg = '强制关联检验检查,无法关联,标记跳过';
            $this->getLogStorage()->insertOne(['text' => $msg, 'data' => $th->getMessage()], LogStatus::ERROR);
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
    public function generateBatchRequestParams($data)
    {
        $new = [];
        foreach ($data as $key => $item) {
            $this->Collation->setData($item);
            $request = $this->Collation->run($this->metaData['request']);
            $other =  $this->Collation->run($this->metaData['otherRequest']);
            $key = $other['key'];
            $new[$key][] = $request;
        }
        return $new;
    }

    public function handleResponse($response, $jobId = null)
    {
        if (!isset($response['errorCode'])) {
            return $this->handleError($response, $jobId);
        }
//        if ($response['errorCode'] != 0) {
//            return $this->handleError($response, $jobId);
//        }
        if (!isset($response['data'])) {
            return $this->handleError($response, $jobId);
        }
        if(!isset($response['data']['result'])){
            return $this->handleError($response, $jobId);
        }
        //先把全部设为错误，再循环把成功的设为已完成
        $this->getAsynTargetJobStorage()->updateResponse($jobId, DataStatus::ERROR, $response, [], null, $this->active);
        foreach ($response['data']['result'] as $result){
            if($result['billStatus']){
                $this->getLogStorage()->insertOne(['text' => '_handle_merge_noto|' . LogMessage::INVOKE_FAIL, 'item' => $result, 'jobId' => $jobId], LogStatus::ERROR);
                $this->getAsynTargetJobStorage()->updateResponse($jobId, DataStatus::FINISHED, $result, [$result['billIndex']], $result['id'],   $this->active);
                $this->handleSuccessCallback($response, $jobId);
            }else if($result['billIndex'] >= 0){

            }else{
                $this->handleEachItemError($result, $jobId);
            }
        }


        if (isset($this->metaData['autoCheck'])) {
            $this->_autoCheck($response);
        }
        return $response;
    }


    public function handleError($response, $jobId = null)
    {
        $this->getLogStorage()->insertOne(['text' => LogMessage::EXEC_JOB_RESPONSE_ERROR, 'response' => $response], LogStatus::ERROR);
        $throw = new KdGalaxyThrowable($this);
        $throw->handle($jobId, $response);
        $this->getAsynTargetJobStorage()->updateResponse($jobId, DataStatus::ERROR, $response, [], null, $this->active);
//        $this->reQueue();
    }

    public function handleEachItemError($result, $jobId = null)
    {
        $this->getLogStorage()->insertOne(['text' => LogMessage::EXEC_JOB_RESPONSE_ERROR, 'response' => $result], LogStatus::ERROR);
        $throw = new KdGalaxyThrowable($this);
        $throw->handle($jobId, $result);
        $this->getAsynTargetJobStorage()->updateResponse($jobId, DataStatus::ERROR, $result, [$result['billIndex']], null, $this->active);
//        $this->reQueue();
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
