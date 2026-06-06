<?php

namespace Adapter\KdGalaxy\SDK;

use Illuminate\Support\Facades\Cache;
use Domain\Datahub\Connector\ConnectorRepository;
use Domain\Datahub\Model\ConnectorModel;
use Exception;
// 金蝶云星空旗舰版

class KdGalaxySDK
{
    protected $connectorId = 'connectorId';
    protected $env = '';
    private $host = 'https://yifanni.kdgalaxy.com';
    private $login = [
        'host' => 'https://yifanni.kdgalaxy.com',
        'client_id' => 'sxsxxxxx',
        'client_secret' => 'xxxxxxxxx',
        'username' => 'xxxxxxxxxx',
        'accountId' => 'xxxxxxxxxx',
        'language' => 'zh_CN',
        'x-acgw-identity' => '',
    ];

    public $token = null;
    public $access_token = null;
    private $validity = 3600;
    private $error = [];
    public $client = \GuzzleHttp\Client::class;

    public function __construct($connectorId, $params, $env)
    {
        $this->connectorId = $connectorId;
        $this->login = $params;
        $this->env = $env;
        $this->host = $params['host'];
        $this->client = new \GuzzleHttp\Client();
    }

    public function invoke(string $api, $params, $method = 'POST')
    {
        $params = json_encode($params,JSON_UNESCAPED_UNICODE);
        $params = json_decode($params, true);
        $url = $this->host . $api;
        $headers = [
            'Content-Type' => 'application/json;charset=utf-8',
            'accesstoken' => $this->token ?? '',
            'x-acgw-identity' => $this->login['x-acgw-identity'] ?? '',
            'Accept' => 'application/json'
        ];
        try {
            if (strtolower($method) === 'get') {
                $response = $this->client->get($url, ['body' => json_encode($params), 'http_errors' => false, 'headers' => $headers]);
            } else {
                $jsonBody = json_encode($params, JSON_UNESCAPED_UNICODE);
                $response = $this->client->post($url, ['body' => $jsonBody, 'http_errors' => false, 'headers' => $headers]);
            }
        } catch (\Throwable $e) {
            return ['success' => false, 'errorCode' => 'fail', 'message' => '金蝶请求超时', 'data' => $e->getMessage()];
        }

        $body = $response->getBody();
        $bodyStr = (string)$body;
        $arr = json_decode($bodyStr, true);
        $arr = $this->changeKey($arr);
        return $arr;
    }
    /**
     * 上传文件到指定API接口
     *
     * @param string $api 接口路径
     * @param array $params 请求参数，需包含文件和表单数据
     * @param string $method 请求方法，默认为POST
     * @return mixed
     * @throws \Exception
     */
    public function uploadFile(string $api, array $params, string $method = 'POST')
    {
        $url = $this->host . $api;

        // 设置请求头
        $headers = [
            'Accept' => 'application/json',
            'accesstoken' => $this->token ?? '',
            'x-acgw-identity' => $this->login['x-acgw-identity'] ?? '',
            'Accept-Encoding' => 'gzip, deflate, br'
        ];

        // 准备multipart数据
        $multipart = [];

        // 处理文件上传
        if (!empty($params['file'])) {
            $filePath = $params['file'];
            if (!file_exists($filePath)) {
                throw new \Exception("文件不存在: {$filePath}");
            }
            unset($params['file']);

            $multipart[] = [
                'name' => 'file',
                'contents' => fopen($filePath, 'r'),
                'filename' => basename($filePath)
            ];
        }

        // 处理表单参数（特别是parameter字段）
        if (!empty($params['parameter'])) {
            $multipart[] = [
                'name' => 'parameter',
                'contents' => is_array($params['parameter']) ?
                    json_encode($params['parameter']) :
                    $params['parameter']
            ];
        }

        try {
            // 发送请求
            $response = $this->client->request($method, $url, [
                'headers' => $headers,
                'multipart' => $multipart,
                'http_errors' => false // 禁用抛出HTTP错误异常
            ]);

            // 处理响应
            $statusCode = $response->getStatusCode();
            $responseBody = $response->getBody()->getContents();

            if ($statusCode >= 400) {
                throw new \Exception("API请求失败: {$statusCode}, 响应: {$responseBody}");
            }

            return json_decode($responseBody, true) ?: $responseBody;
        } catch (\Exception $e) {
            throw new \Exception("上传文件请求失败: " . $e->getMessage());
        }
    }

    public function connection()
    {
        $cacheKey = $this->connectorId . $this->env;
        $token = Cache::get($cacheKey);
        if ($token) {
            $this->token = $token;
            if ($this->login['expires_time'] - time() < 0) {
                $this->refreshToken();
            }
            return ['status' => true, 'token' => $token];
        }

        $hostHasKapi = strpos($this->host, '/kapi') !== false;
        if ($hostHasKapi) {
            $url = $this->host . '/oauth2/getToken';
        } else {
            $url = $this->host . '/kapi/oauth2/getToken';
        }
        $timestamp = date('Y-m-d H:i:s');
        $request = [
            'client_id' => $this->login['client_id'],
            'client_secret' => $this->login['client_secret'],
            'username' => $this->login['username'],
            'accountId' => $this->login['accountId'],
            'language' => $this->login['language'],
            'nonce' => bin2hex(random_bytes(16)),
            'timestamp' => $timestamp
        ];
        $headers = [
            'Content-Type' => 'application/json',
            'Accept' => 'application/json'
        ];

        $response = $this->client->post($url, ['body' => json_encode($request), 'headers' => $headers]);
        $body = $response->getBody();
        $bodyStr = (string)$body;
        $arr = json_decode($bodyStr, true);

        if (isset($arr['errorCode']) && $arr['errorCode'] == '0') {
            $model = ConnectorModel::find($this->connectorId);
            $envkey = 'env_' . $model->env . '_params';
            $envparams = $model->$envkey;
            $envparams['access_token'] = $arr['data']['access_token'];
            $envparams['refresh_token'] = $arr['data']['refresh_token'];
            // 设置过期时间为当前时间加上expires_in
            $expires_in_seconds = $arr['data']['expires_in'] / 1000;
            $envparams['expires_time'] = time() + $expires_in_seconds - 300;
            $model->$envkey  = $envparams;
            $this->access_token =  $arr['data']['access_token'];
            $this->validity = $expires_in_seconds - 300;
            // 写入数据库
            $model->save();
            $this->token = $this->access_token;
            ConnectorRepository::hardRefresh($this->connectorId);
            Cache::put(
                $cacheKey,
                $this->access_token,
                $this->validity,
            );
            return ['status' => true, 'res' => $arr];
        } else {
            $this->error = $arr;
            return ['status' => false, 'res' => $arr];
        }
    }
    // 获取access_token方法

    public function refreshToken()
    {
        $cacheKey = $this->connectorId . $this->env;
        $hostHasKapi = strpos($this->host, '/kapi') !== false;
        if ($hostHasKapi) {
            $url = $this->host . '/oauth2/refreshToken';
        } else {
            $url = $this->host . '/kapi/oauth2/refreshToken';
        }
        $timestamp = date('Y-m-d H:i:s');
        $request = [
            'client_id' => $this->login['client_id'],
            'grant_type' => 'refresh_token',
            'refresh_token' => $this->login['refresh_token'],
            'accountId' => $this->login['accountId'],
            'nonce' => bin2hex(random_bytes(16)),
            'timestamp' => $timestamp
        ];
        $headers = [
            'Content-Type' => 'application/json',
            'Accept' => 'application/json'
        ];

        $response = $this->client->post($url, ['body' => json_encode($request), 'headers' => $headers]);
        $body = $response->getBody();
        $bodyStr = (string)$body;
        $arr = json_decode($bodyStr, true);

        if (isset($arr['errorCode']) && $arr['errorCode'] == '0') {
            $model = ConnectorModel::find($this->connectorId);
            $envkey = 'env_' . $model->env . '_params';
            $envparams = $model->$envkey;
            $envparams['access_token'] = $arr['data']['access_token'];
            $envparams['refresh_token'] = $arr['data']['refresh_token'];
            // 设置过期时间为当前时间加上expires_in
            $expires_in_seconds = $arr['data']['expires_in'] / 1000;
            $envparams['expires_time'] = time() + $expires_in_seconds - 300;
            $model->$envkey  = $envparams;
            $this->access_token =  $arr['data']['access_token'];
            $this->validity = $expires_in_seconds - 300;
            // 写入数据库
            $model->save();
            ConnectorRepository::hardRefresh($this->connectorId);
            Cache::put(
                $cacheKey,
                $this->access_token,
                $this->validity,
            );
        }
        return $arr;
    }

    public function changeKey($response)
    {
        if (is_array($response)) {
            $newResponse = [];
            foreach ($response as $key => $val) {
                $newKey = str_replace('.', '_', $key);
                $newResponse[$newKey] = $this->changeKey($val);
            }
            return $newResponse;
        } elseif (is_object($response)) {
            $newResponse = new \stdClass();
            foreach ($response as $key => $val) {
                $newKey = str_replace('.', '_', $key);
                $newResponse->$newKey = $this->changeKey($val);
            }
            return $newResponse;
        }
        return $response;
    }
}
