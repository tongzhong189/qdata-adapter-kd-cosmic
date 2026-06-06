<?php

namespace Adapter\KdGalaxy\Throwable;

use Domain\Datahub\Instance\Adapter\InvokeThrowable;
use Illuminate\Support\Facades\Log;

class KdGalaxyThrowable extends InvokeThrowable
{

    public function handle($jobId, $response)
    {
        parent::handle($jobId, $response);
        $this->_parserResponse();
        $this->_callbackData();
    }

    private function _parserResponse()
    {
        if (empty($this->response) || $this->response == null || !$this->response) {
            $this->putResult(
                [
                    'text' => '云星空旗舰版响应数据为空',
                    'problem' => '',
                    'cause_analysis' => null,
                    'solution' => null,
                    'link' => null,
                    'id' => null
                ]
            );
            return;
        }
        $msg = '';
        if (isset($this->response['message'])) {
            $msg .= $this->response['message'];
        }
        if (isset($this->response['description'])) {
            $msg = $this->response['description'];
        }
        if (isset($this->response['description_cn'])) {
            $msg = $this->response['description_cn'];
        }
        if(isset($this->response['data'])){
            if(isset($this->response['data']['errorInfo'])){
                $msg = '';
                foreach ($this->response['data']['errorInfo'] as $row) {
                    $msg .= $row['msg'];
                }
            }
        }
        if (isset($this->response['errors']) && count($this->response['errors']) > 0 ) {
            $msg = $this->response['errors'][0]['rowMsg'][0] ?? '';
        }


        if (strpos($msg, "ERROR: duplicate key value violates") !== false) {
            $this->putResult(
                [
                    'text' => '云星空旗舰版数据库写入失败',
                    'problem' => $msg,
                ]
            );
            return;
        }
        if (strpos($msg, "For input string:") !== false) {
            $this->putResult(
                [
                    'text' => '输入的字符串内容错误',
                    'problem' => $msg,
                ]
            );
            return;
        }
        $this->putResult(
            [
                'text' => $msg,
                'problem' => $msg,
            ]
        );
    }
}
