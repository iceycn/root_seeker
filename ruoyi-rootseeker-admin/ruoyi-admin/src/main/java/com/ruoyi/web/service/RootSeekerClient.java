package com.ruoyi.web.service;

import java.io.UnsupportedEncodingException;
import java.net.URLEncoder;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.client.HttpClientErrorException;
import org.springframework.web.client.RestTemplate;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruoyi.common.utils.StringUtils;
import com.ruoyi.framework.web.service.ConfigService;
import com.ruoyi.web.config.RootSeekerConfig;

/**
 * RootSeeker HTTP 客户端：拉取仓库列表、同步等
 * baseUrl 优先从 sys_config（root.seeker.baseUrl）读取，未配置时使用 application.yml 默认值
 */
@Service
public class RootSeekerClient {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final String CONFIG_KEY_BASE_URL = "root.seeker.baseUrl";
    private static final String CONFIG_KEY_ADMIN_CALLBACK_URL = "root.seeker.adminCallbackUrl";

    @Autowired
    private RootSeekerConfig config;
    @Autowired
    private RestTemplate restTemplate;
    @Autowired
    private ConfigService configService;

    /** 获取 RootSeeker 服务地址，优先从 sys_config 读取 */
    private String getBaseUrl() {
        String url = configService != null ? configService.getKey(CONFIG_KEY_BASE_URL) : null;
        return StringUtils.isNotEmpty(url) ? url.trim() : config.getBaseUrl();
    }

    /** 获取 Admin 回调地址，用于 RootSeeker 任务完成后通知。优先 sys_config，否则 yaml。未配置时返回 null */
    private String getAdminCallbackUrl() {
        String url = configService != null ? configService.getKey(CONFIG_KEY_ADMIN_CALLBACK_URL) : null;
        if (StringUtils.isNotEmpty(url)) return url.trim();
        url = config != null && config.getAdminCallbackUrl() != null ? config.getAdminCallbackUrl() : "";
        return StringUtils.isNotEmpty(url) ? url.trim() : null;
    }

    /** 从 RootSeeker 4xx 响应中提取 detail 信息（FastAPI 格式：{"detail": "..."} 或 {"detail": [...]}） */
    private String extractDetail(HttpClientErrorException e) {
        String body = e.getResponseBodyAsString();
        if (body == null || body.isEmpty()) return e.getStatusCode() + " " + e.getStatusText();
        try {
            JsonNode node = JSON.readTree(body);
            JsonNode detail = node.get("detail");
            if (detail != null && !detail.isNull()) {
                if (detail.isArray() && detail.size() > 0)
                    return detail.get(0).get("msg") != null ? detail.get(0).get("msg").asText() : detail.toString();
                return detail.asText();
            }
        } catch (Exception ignored) { }
        return body.length() > 200 ? body.substring(0, 200) + "..." : body;
    }

    private HttpHeaders createHeaders() {
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        if (config.getApiKey() != null && !config.getApiKey().isEmpty()) {
            headers.set("X-Api-Key", config.getApiKey());
        }
        return headers;
    }

    /** URL 编码，兼容 Java 8（encode(String, Charset) 需 Java 10+） */
    private static String urlEncode(String s) {
        try {
            return URLEncoder.encode(s, "UTF-8");
        } catch (UnsupportedEncodingException e) {
            throw new RuntimeException("UTF-8 not supported", e);
        }
    }

    /**
     * 验证凭证是否有效（不保存）。拉取前可先调用此接口探测账号密码是否正确。
     */
    @SuppressWarnings("unchecked")
    public Map<String, Object> verifyCredentials(String domain, String username, String password, String platform) {
        String url = getBaseUrl() + "/git-source/verify";
        Map<String, Object> body = new HashMap<>();
        body.put("domain", domain);
        body.put("username", username);
        body.put("password", password);
        if (platform != null && !platform.isEmpty()) {
            body.put("platform", platform);
        }
        HttpEntity<Map<String, Object>> entity = new HttpEntity<>(body, createHeaders());
        try {
            ResponseEntity<Map> resp = restTemplate.exchange(url, HttpMethod.POST, entity, Map.class);
            return resp.getBody() != null ? resp.getBody() : new HashMap<>();
        } catch (HttpClientErrorException e) {
            throw new RuntimeException(extractDetail(e), e);
        }
    }

    /**
     * 保存凭证并拉取仓库列表
     */
    @SuppressWarnings("unchecked")
    public Map<String, Object> connectAndFetchRepos(String domain, String username, String password, String platform) {
        String url = getBaseUrl() + "/git-source/config";
        Map<String, Object> body = new HashMap<>();
        body.put("domain", domain);
        body.put("username", username);
        body.put("password", password);
        if (platform != null && !platform.isEmpty()) {
            body.put("platform", platform);
        }
        HttpEntity<Map<String, Object>> entity = new HttpEntity<>(body, createHeaders());
        try {
            ResponseEntity<Map> resp = restTemplate.exchange(url, HttpMethod.PUT, entity, Map.class);
            return resp.getBody() != null ? resp.getBody() : new HashMap<>();
        } catch (HttpClientErrorException e) {
            throw new RuntimeException(extractDetail(e), e);
        }
    }

    /**
     * 同步所有已启用仓库。callback_url 可选
     */
    @SuppressWarnings("unchecked")
    public Map<String, Object> syncRepos() {
        String base = getBaseUrl() + "/git-source/sync";
        String cb = getAdminCallbackUrl();
        if (cb != null && !cb.isEmpty()) {
            base += "?callback_url=" + urlEncode(cb);
        }
        HttpEntity<Void> entity = new HttpEntity<>(createHeaders());
        ResponseEntity<Map> resp = restTemplate.exchange(base, HttpMethod.POST, entity, Map.class);
        return resp.getBody() != null ? resp.getBody() : new HashMap<>();
    }

    /**
     * 同步单个仓库（仓库同步：git clone/pull）。callback_url 可选，同步完成后 RootSeeker 可能触发后续索引入队并回调
     */
    @SuppressWarnings("unchecked")
    public Map<String, Object> syncSingleRepo(String serviceName) {
        String encoded = serviceName != null ? serviceName.replace("/", "%2F") : "";
        String base = getBaseUrl() + "/repos/sync?service_name=" + encoded;
        String cb = getAdminCallbackUrl();
        if (cb != null && !cb.isEmpty()) {
            base += "&callback_url=" + urlEncode(cb);
        }
        HttpEntity<Void> entity = new HttpEntity<>(createHeaders());
        ResponseEntity<Map> resp = restTemplate.exchange(base, HttpMethod.POST, entity, Map.class);
        return resp.getBody() != null ? resp.getBody() : new HashMap<>();
    }

    /**
     * 获取仓库详情（含分支列表）
     * @param branchSearch 可选，分支搜索关键字，用于过滤分支列表
     */
    @SuppressWarnings("unchecked")
    public Map<String, Object> getRepoDetail(String repoId, String branchSearch) {
        String base = getBaseUrl() + "/git-source/repos/" + repoId.replace("/", "%2F");
        String url = (branchSearch != null && !branchSearch.isEmpty())
            ? base + "?branch_search=" + urlEncode(branchSearch)
            : base;
        HttpEntity<Void> entity = new HttpEntity<>(createHeaders());
        ResponseEntity<Map> resp = restTemplate.exchange(url, HttpMethod.GET, entity, Map.class);
        return resp.getBody() != null ? resp.getBody() : new HashMap<>();
    }

    /**
     * 配置仓库（分支、启用状态）
     */
    @SuppressWarnings("unchecked")
    public Map<String, Object> configureRepo(String repoId, List<String> branches, boolean enabled) {
        String url = getBaseUrl() + "/git-source/repos/" + repoId.replace("/", "%2F");
        Map<String, Object> body = new HashMap<>();
        body.put("branches", branches != null ? branches : Collections.emptyList());
        body.put("enabled", enabled);
        String cb = getAdminCallbackUrl();
        if (cb != null && !cb.isEmpty()) {
            body.put("callback_url", cb);
        }
        HttpEntity<Map<String, Object>> entity = new HttpEntity<>(body, createHeaders());
        ResponseEntity<Map> resp = restTemplate.exchange(url, HttpMethod.PUT, entity, Map.class);
        return resp.getBody() != null ? resp.getBody() : new HashMap<>();
    }

    // ---------- 应用配置 API（config_source、llm、embedding 等，需 RootSeeker 配置 config_db） ----------

    /** 获取全部应用配置（按分类） */
    @SuppressWarnings("unchecked")
    public Map<String, Object> appConfigList() {
        String url = getBaseUrl() + "/app-config";
        HttpEntity<Void> entity = new HttpEntity<>(createHeaders());
        ResponseEntity<Map> resp = restTemplate.exchange(url, HttpMethod.GET, entity, Map.class);
        return resp.getBody() != null ? resp.getBody() : new HashMap<>();
    }

    /** 获取配置来源（file / database） */
    @SuppressWarnings("unchecked")
    public Map<String, Object> getConfigSource() {
        String url = getBaseUrl() + "/app-config/system";
        HttpEntity<Void> entity = new HttpEntity<>(createHeaders());
        ResponseEntity<Map> resp = restTemplate.exchange(url, HttpMethod.GET, entity, Map.class);
        return resp.getBody() != null ? resp.getBody() : new HashMap<>();
    }

    /** 设置配置来源 */
    @SuppressWarnings("unchecked")
    public Map<String, Object> setConfigSource(String source) {
        String url = getBaseUrl() + "/app-config/system";
        Map<String, Object> body = new HashMap<>();
        body.put("config_source", source);
        HttpEntity<Map<String, Object>> entity = new HttpEntity<>(body, createHeaders());
        ResponseEntity<Map> resp = restTemplate.exchange(url, HttpMethod.PUT, entity, Map.class);
        return resp.getBody() != null ? resp.getBody() : new HashMap<>();
    }

    /** 获取指定分类配置 */
    @SuppressWarnings("unchecked")
    public Map<String, Object> getConfigCategory(String category) {
        String url = getBaseUrl() + "/app-config/" + category;
        HttpEntity<Void> entity = new HttpEntity<>(createHeaders());
        ResponseEntity<Map> resp = restTemplate.exchange(url, HttpMethod.GET, entity, Map.class);
        return resp.getBody() != null ? resp.getBody() : new HashMap<>();
    }

    /** 保存指定分类配置 */
    @SuppressWarnings("unchecked")
    public Map<String, Object> saveConfigCategory(String category, Map<String, Object> config) {
        String url = getBaseUrl() + "/app-config/" + category;
        HttpEntity<Map<String, Object>> entity = new HttpEntity<>(config != null ? config : new HashMap<>(), createHeaders());
        ResponseEntity<Map> resp = restTemplate.exchange(url, HttpMethod.PUT, entity, Map.class);
        return resp.getBody() != null ? resp.getBody() : new HashMap<>();
    }

    /** 配置变更通知：保存配置后调用，通知 RootSeeker 配置已更新 */
    @SuppressWarnings("unchecked")
    public void notifyConfigChanged() {
        try {
            String url = getBaseUrl() + "/app-config/notify";
            HttpEntity<Void> entity = new HttpEntity<>(createHeaders());
            restTemplate.exchange(url, HttpMethod.POST, entity, Map.class);
        } catch (Exception ignored) {
            // 通知失败不阻塞主流程，仅记录
        }
    }

    /** 仓库变更通知：拉取/编辑/同步仓库后调用，通知 RootSeeker 刷新 catalog */
    @SuppressWarnings("unchecked")
    public void notifyRepoChanged() {
        try {
            String url = getBaseUrl() + "/git-source/notify";
            HttpEntity<Void> entity = new HttpEntity<>(createHeaders());
            restTemplate.exchange(url, HttpMethod.POST, entity, Map.class);
        } catch (Exception ignored) {
            // 通知失败不阻塞主流程，仅记录
        }
    }

    // ---------- 索引管理 API ----------

    /** 获取各仓库的 Qdrant 与 Zoekt 索引状态 */
    @SuppressWarnings("unchecked")
    public Map<String, Object> getIndexStatus() {
        String url = getBaseUrl() + "/index/status";
        HttpEntity<Void> entity = new HttpEntity<>(createHeaders());
        ResponseEntity<Map> resp = restTemplate.exchange(url, HttpMethod.GET, entity, Map.class);
        return resp.getBody() != null ? resp.getBody() : new HashMap<>();
    }

    /** 为指定仓库建向量索引。callback_url 可选，任务完成后 RootSeeker 会 POST 回调 */
    @SuppressWarnings("unchecked")
    public Map<String, Object> indexRepo(String serviceName, boolean incremental) {
        String base = getBaseUrl() + "/index/repo/" + serviceName.replace("/", "%2F") + "?incremental=" + incremental;
        String cb = getAdminCallbackUrl();
        if (cb != null && !cb.isEmpty()) {
            base += "&callback_url=" + urlEncode(cb);
        }
        HttpEntity<Void> entity = new HttpEntity<>(createHeaders());
        ResponseEntity<Map> resp = restTemplate.exchange(base, HttpMethod.POST, entity, Map.class);
        return resp.getBody() != null ? resp.getBody() : new HashMap<>();
    }

    /** 清除指定仓库向量并重新全量索引。callback_url 可选 */
    @SuppressWarnings("unchecked")
    public Map<String, Object> resetRepoIndex(String serviceName) {
        String base = getBaseUrl() + "/index/repo/" + serviceName.replace("/", "%2F") + "/reset";
        String cb = getAdminCallbackUrl();
        if (cb != null && !cb.isEmpty()) {
            base += "?callback_url=" + urlEncode(cb);
        }
        HttpEntity<Void> entity = new HttpEntity<>(createHeaders());
        ResponseEntity<Map> resp = restTemplate.exchange(base, HttpMethod.POST, entity, Map.class);
        return resp.getBody() != null ? resp.getBody() : new HashMap<>();
    }

    /** 为指定仓库建 Zoekt 索引。callback_url 可选 */
    @SuppressWarnings("unchecked")
    public Map<String, Object> indexZoektRepo(String serviceName) {
        String base = getBaseUrl() + "/index/zoekt/" + serviceName.replace("/", "%2F");
        String cb = getAdminCallbackUrl();
        if (cb != null && !cb.isEmpty()) {
            base += "?callback_url=" + urlEncode(cb);
        }
        HttpEntity<Void> entity = new HttpEntity<>(createHeaders());
        try {
            ResponseEntity<Map> resp = restTemplate.exchange(base, HttpMethod.POST, entity, Map.class);
            return resp.getBody() != null ? resp.getBody() : new HashMap<>();
        } catch (HttpClientErrorException e) {
            throw new RuntimeException(extractDetail(e), e);
        }
    }

    /** 获取索引任务详情（含日志） */
    @SuppressWarnings("unchecked")
    public Map<String, Object> getIndexJob(String jobId) {
        String url = getBaseUrl() + "/index/job/" + (jobId != null ? jobId.replace("/", "%2F") : "");
        HttpEntity<Void> entity = new HttpEntity<>(createHeaders());
        try {
            ResponseEntity<Map> resp = restTemplate.exchange(url, HttpMethod.GET, entity, Map.class);
            return resp.getBody() != null ? resp.getBody() : new HashMap<>();
        } catch (HttpClientErrorException e) {
            throw new RuntimeException(extractDetail(e), e);
        }
    }

    /** 获取索引队列列表（供 Admin 队列调度展示） */
    @SuppressWarnings("unchecked")
    public Map<String, Object> getIndexQueue() {
        String url = getBaseUrl() + "/index/queue";
        HttpEntity<Void> entity = new HttpEntity<>(createHeaders());
        try {
            ResponseEntity<Map> resp = restTemplate.exchange(url, HttpMethod.GET, entity, Map.class);
            return resp.getBody() != null ? resp.getBody() : new HashMap<>();
        } catch (HttpClientErrorException e) {
            throw new RuntimeException(extractDetail(e), e);
        }
    }

    /** 清除指定仓库向量（仅清除，不重索引）。callback_url 可选 */
    @SuppressWarnings("unchecked")
    public Map<String, Object> clearRepoIndex(String serviceName) {
        String base = getBaseUrl() + "/index/repo/" + serviceName.replace("/", "%2F") + "/clear";
        String cb = getAdminCallbackUrl();
        if (cb != null && !cb.isEmpty()) {
            base += "?callback_url=" + urlEncode(cb);
        }
        HttpEntity<Void> entity = new HttpEntity<>(createHeaders());
        ResponseEntity<Map> resp = restTemplate.exchange(base, HttpMethod.POST, entity, Map.class);
        return resp.getBody() != null ? resp.getBody() : new HashMap<>();
    }

    /** 重新同步：先清除后添加，添加完成后触发依赖图重建。callback_url 可选 */
    @SuppressWarnings("unchecked")
    public Map<String, Object> resyncRepoIndex(String serviceName) {
        String base = getBaseUrl() + "/index/repo/" + serviceName.replace("/", "%2F") + "/resync";
        String cb = getAdminCallbackUrl();
        if (cb != null && !cb.isEmpty()) {
            base += "?callback_url=" + urlEncode(cb);
        }
        HttpEntity<Void> entity = new HttpEntity<>(createHeaders());
        ResponseEntity<Map> resp = restTemplate.exchange(base, HttpMethod.POST, entity, Map.class);
        return resp.getBody() != null ? resp.getBody() : new HashMap<>();
    }

    /** 清除全部向量，可选重索引。callback_url 可选 */
    @SuppressWarnings("unchecked")
    public Map<String, Object> resetAllIndex(boolean reindex) {
        String base = getBaseUrl() + "/index/reset-all?reindex=" + reindex;
        String cb = getAdminCallbackUrl();
        if (cb != null && !cb.isEmpty()) {
            base += "&callback_url=" + urlEncode(cb);
        }
        HttpEntity<Void> entity = new HttpEntity<>(createHeaders());
        ResponseEntity<Map> resp = restTemplate.exchange(base, HttpMethod.POST, entity, Map.class);
        return resp.getBody() != null ? resp.getBody() : new HashMap<>();
    }

    /** 全量重载：同步 + 清除向量 + 重索引，serviceName 可选。callback_url 可选 */
    @SuppressWarnings("unchecked")
    public Map<String, Object> fullReloadRepos(String serviceName) {
        StringBuilder sb = new StringBuilder(getBaseUrl()).append("/repos/full-reload");
        java.util.List<String> params = new java.util.ArrayList<>();
        if (serviceName != null && !serviceName.isEmpty()) {
            params.add("service_name=" + serviceName.replace("/", "%2F"));
        }
        String cb = getAdminCallbackUrl();
        if (cb != null && !cb.isEmpty()) {
            params.add("callback_url=" + urlEncode(cb));
        }
        if (!params.isEmpty()) {
            sb.append("?").append(String.join("&", params));
        }
        HttpEntity<Void> entity = new HttpEntity<>(createHeaders());
        ResponseEntity<Map> resp = restTemplate.exchange(sb.toString(), HttpMethod.POST, entity, Map.class);
        return resp.getBody() != null ? resp.getBody() : new HashMap<>();
    }

    /**
     * 获取仓库列表（config.repos + git_source 已启用），供异常测试等项目选择。配置模式使用。
     */
    @SuppressWarnings("unchecked")
    public Map<String, Object> getReposList() {
        String url = getBaseUrl() + "/repos/list";
        HttpEntity<Void> entity = new HttpEntity<>(createHeaders());
        ResponseEntity<Map> resp = restTemplate.exchange(url, HttpMethod.GET, entity, Map.class);
        return resp.getBody() != null ? resp.getBody() : new HashMap<>();
    }

    /**
     * 提交错误日志到 RootSeeker 分析（POST /ingest）
     */
    @SuppressWarnings("unchecked")
    public Map<String, Object> ingest(Map<String, Object> event) {
        String url = getBaseUrl() + "/ingest";
        HttpEntity<Map<String, Object>> entity = new HttpEntity<>(event != null ? event : new HashMap<>(), createHeaders());
        ResponseEntity<Map> resp = restTemplate.exchange(url, HttpMethod.POST, entity, Map.class);
        return resp.getBody() != null ? resp.getBody() : new HashMap<>();
    }

    /**
     * 根据 analysis_id 查询分析结果或状态（GET /analysis/{analysis_id}）
     */
    @SuppressWarnings("unchecked")
    public Map<String, Object> getAnalysis(String analysisId) {
        if (analysisId == null || analysisId.isEmpty()) {
            throw new IllegalArgumentException("analysis_id 不能为空");
        }
        String url = getBaseUrl() + "/analysis/" + analysisId.replace("/", "%2F");
        HttpEntity<Void> entity = new HttpEntity<>(createHeaders());
        try {
            ResponseEntity<Map> resp = restTemplate.exchange(url, HttpMethod.GET, entity, Map.class);
            return resp.getBody() != null ? resp.getBody() : new HashMap<>();
        } catch (HttpClientErrorException e) {
            throw new RuntimeException(extractDetail(e), e);
        }
    }
}
