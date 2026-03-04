package com.ruoyi.web.controller.gitsource;

import java.util.Arrays;
import java.util.Collections;
import java.util.Date;
import java.util.List;
import java.util.Map;
import org.apache.shiro.authz.annotation.RequiresPermissions;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Controller;
import org.springframework.ui.ModelMap;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseBody;
import com.ruoyi.common.annotation.Anonymous;
import com.ruoyi.common.annotation.Log;
import com.ruoyi.common.core.controller.BaseController;
import com.ruoyi.common.core.domain.AjaxResult;
import com.ruoyi.common.core.page.TableDataInfo;
import com.ruoyi.common.enums.BusinessType;
import com.ruoyi.common.utils.StringUtils;
import com.ruoyi.system.domain.GitSourceCredential;
import com.ruoyi.system.domain.GitSourceRepo;
import com.ruoyi.system.domain.SysConfig;
import com.ruoyi.system.domain.RepoIndexStatus;
import com.ruoyi.system.service.IGitSourceCredentialService;
import com.ruoyi.system.service.IGitSourceRepoService;
import com.ruoyi.system.service.IRepoIndexStatusService;
import com.ruoyi.system.service.ISysConfigService;
import com.ruoyi.web.component.IndexCallbackQueue;
import com.ruoyi.web.config.RootSeekerConfig;
import com.ruoyi.web.service.RootSeekerClient;

/**
 * Git 仓库管理（RootSeeker 异构集成）
 */
@Controller
@RequestMapping("/gitsource")
public class GitSourceController extends BaseController {
    private static final Logger log = LoggerFactory.getLogger(GitSourceController.class);
    private String prefix = "gitsource";
    private static final String CONFIG_KEY_BASE_URL = "root.seeker.baseUrl";
    private static final String CONFIG_KEY_ADMIN_CALLBACK_URL = "root.seeker.adminCallbackUrl";

    @Autowired
    private IGitSourceRepoService repoService;
    @Autowired
    private IGitSourceCredentialService credentialService;
    @Autowired
    private ISysConfigService sysConfigService;
    @Autowired
    private RootSeekerClient rootSeekerClient;
    @Autowired
    private IRepoIndexStatusService repoIndexStatusService;
    @Autowired
    private IndexCallbackQueue indexCallbackQueue;
    @Autowired(required = false)
    private RootSeekerConfig rootSeekerConfig;

    @RequiresPermissions("gitsource:repo:view")
    @GetMapping("/repo")
    public String repo() {
        return prefix + "/repo";
    }

    @RequiresPermissions("gitsource:repo:list")
    @PostMapping("/repo/list")
    @ResponseBody
    public TableDataInfo repoList(GitSourceRepo repo) {
        startPage();
        List<GitSourceRepo> list = repoService.selectRepoList(repo);
        return getDataTable(list);
    }

    @RequiresPermissions("gitsource:repo:edit")
    @GetMapping("/repo/edit")
    public String repoEdit(@RequestParam("id") String id, ModelMap mmap) {
        GitSourceRepo repo = repoService.selectRepoById(id);
        mmap.put("repo", repo);
        return prefix + "/repoEdit";
    }

    @RequiresPermissions("gitsource:repo:edit")
    @Log(title = "Git仓库", businessType = BusinessType.UPDATE)
    @PostMapping("/repo/edit")
    @ResponseBody
    public AjaxResult repoEditSave(
            @RequestParam String id,
            @RequestParam(required = false) String fullName,
            @RequestParam(required = false) String gitUrl,
            @RequestParam(required = false) String defaultBranch,
            @RequestParam(value = "branches", required = false) String branchesStr,
            @RequestParam(value = "enabled", defaultValue = "true") Boolean enabled) {
        GitSourceRepo repo = repoService.selectRepoById(id);
        if (repo == null) {
            return error("仓库不存在");
        }
        List<String> branches = branchesStr != null && !branchesStr.isEmpty()
            ? Arrays.asList(branchesStr.trim().split("\\s*,\\s*"))
            : Collections.singletonList(repo.getDefaultBranch() != null ? repo.getDefaultBranch() : "main");
        branches = branches.stream().map(String::trim).filter(s -> !s.isEmpty()).collect(java.util.stream.Collectors.toList());
        if (branches.isEmpty()) {
            branches = Collections.singletonList("main");
        }
        try {
            java.util.Set<String> validNames = new java.util.HashSet<>();
            Map<String, Object> detail = rootSeekerClient.getRepoDetail(id, null);
            Object branchesObj = detail != null ? detail.get("branches") : null;
            if (branchesObj instanceof List) {
                for (Object b : (List<?>) branchesObj) {
                    if (b instanceof Map) {
                        Object name = ((Map<?, ?>) b).get("name");
                        if (name != null && !name.toString().isEmpty()) {
                            validNames.add(name.toString().trim());
                        }
                    }
                }
            }
            if (validNames.isEmpty()) {
                return error("无法获取仓库分支列表，请检查 RootSeeker 连接或稍后重试");
            }
            for (String b : branches) {
                if (!validNames.contains(b)) {
                    return error("分支 " + b + " 不存在，请检查后重试");
                }
            }
        } catch (Exception e) {
            log.warn("校验分支失败: {}", e.getMessage());
            return error("无法校验分支是否存在: " + e.getMessage());
        }
        repo.setEnabled(enabled != null && enabled ? 1 : 0);
        String json = "[\"" + String.join("\",\"", branches) + "\"]";
        repo.setSelectedBranches(json);
        int rows = repoService.updateRepo(repo);
        if (rows > 0) {
            try {
                rootSeekerClient.configureRepo(repo.getId(), branches, repo.getEnabled() == 1);
                rootSeekerClient.notifyRepoChanged();
            } catch (Exception e) {
                return error("本地已更新，但同步到 RootSeeker 失败: " + e.getMessage());
            }
        }
        return toAjax(rows);
    }

    /** 列表页快速切换启用/禁用：启用时调用仓库同步，禁用时调用仓库清除 */
    @RequiresPermissions("gitsource:repo:edit")
    @Log(title = "Git仓库", businessType = BusinessType.UPDATE)
    @PostMapping("/repo/toggleEnabled")
    @ResponseBody
    public AjaxResult repoToggleEnabled(@RequestParam String id, @RequestParam Integer enabled) {
        GitSourceRepo repo = repoService.selectRepoById(id);
        if (repo == null) {
            return error("仓库不存在");
        }
        repo.setEnabled(enabled != null && enabled == 1 ? 1 : 0);
        int rows = repoService.updateRepo(repo);
        if (rows > 0) {
            try {
                List<String> branches = Collections.emptyList();
                if (StringUtils.isNotEmpty(repo.getSelectedBranches())) {
                    try {
                        com.fasterxml.jackson.databind.ObjectMapper om = new com.fasterxml.jackson.databind.ObjectMapper();
                        branches = om.readValue(repo.getSelectedBranches(), java.util.List.class);
                    } catch (Exception ignored) { }
                }
                if (branches.isEmpty() && StringUtils.isNotEmpty(repo.getDefaultBranch())) {
                    branches = Collections.singletonList(repo.getDefaultBranch());
                }
                rootSeekerClient.configureRepo(repo.getId(), branches, repo.getEnabled() == 1);
                rootSeekerClient.notifyRepoChanged();
                // service_name 与 RootSeeker git_source 一致：full_name.replace("/", "-")
                String serviceName = StringUtils.isNotEmpty(repo.getFullName())
                    ? repo.getFullName().replace("/", "-")
                    : (repo.getFullPath() != null ? repo.getFullPath().replace("/", "-") : repo.getId().replace("/", "-"));
                if (repo.getEnabled() == 1) {
                    repoIndexStatusService.setStatus(serviceName, "索引中", "索引中");
                } else {
                    repoIndexStatusService.setStatus(serviceName, "清理中", "清理中");
                    rootSeekerClient.clearRepoIndex(serviceName);
                }
            } catch (Exception e) {
                return error("本地已更新，但同步到 RootSeeker 失败: " + e.getMessage());
            }
        }
        return toAjax(rows);
    }

    /** 获取仓库分支列表（支持搜索），供编辑页下拉使用。无搜索时返回前10条 */
    @RequiresPermissions("gitsource:repo:edit")
    @GetMapping("/repo/branches")
    @ResponseBody
    public AjaxResult repoBranches(@RequestParam String repoId, @RequestParam(required = false) String search) {
        try {
            Map<String, Object> detail = rootSeekerClient.getRepoDetail(repoId, search);
            Object branchesObj = detail != null ? detail.get("branches") : null;
            if (branchesObj == null || !(branchesObj instanceof List)) {
                return success(java.util.Collections.singletonMap("results", java.util.Collections.emptyList()));
            }
            @SuppressWarnings("unchecked")
            List<Map<String, Object>> branches = (List<Map<String, Object>>) branchesObj;
            int limit = (search == null || search.isEmpty()) ? 10 : 50;
            List<Map<String, String>> results = new java.util.ArrayList<>();
            for (int i = 0; i < Math.min(branches.size(), limit); i++) {
                Map<String, Object> b = branches.get(i);
                Object name = b != null ? b.get("name") : null;
                if (name != null && !name.toString().isEmpty()) {
                    Map<String, String> item = new java.util.HashMap<>();
                    item.put("id", name.toString());
                    item.put("text", name.toString());
                    results.add(item);
                }
            }
            Map<String, Object> out = new java.util.HashMap<>();
            out.put("results", results);
            out.put("pagination", java.util.Collections.singletonMap("more", branches.size() > limit));
            return success(out);
        } catch (Exception e) {
            log.warn("获取分支列表失败: {}", e.getMessage());
            return success(java.util.Collections.singletonMap("results", java.util.Collections.emptyList()));
        }
    }

    @RequiresPermissions("gitsource:credential:view")
    @GetMapping("/credential")
    public String credential(ModelMap mmap) {
        mmap.put("credential", credentialService.getCredential());
        return prefix + "/credential";
    }

    @RequiresPermissions("gitsource:config:view")
    @GetMapping("/config")
    public String config(ModelMap mmap) {
        SysConfig cfg = sysConfigService.selectConfigByKeyEntity(CONFIG_KEY_BASE_URL);
        String baseUrl = cfg != null ? cfg.getConfigValue() : "http://localhost:8000";
        mmap.put("baseUrl", baseUrl);
        SysConfig cbCfg = sysConfigService.selectConfigByKeyEntity(CONFIG_KEY_ADMIN_CALLBACK_URL);
        String cbVal = cbCfg != null && cbCfg.getConfigValue() != null ? cbCfg.getConfigValue() : "";
        if (cbVal.isEmpty() && rootSeekerConfig != null && rootSeekerConfig.getAdminCallbackUrl() != null && !rootSeekerConfig.getAdminCallbackUrl().isEmpty()) {
            cbVal = rootSeekerConfig.getAdminCallbackUrl();
        }
        mmap.put("adminCallbackUrl", cbVal);
        return prefix + "/config";
    }

    @RequiresPermissions("gitsource:config:edit")
    @Log(title = "RootSeeker配置", businessType = BusinessType.UPDATE)
    @PostMapping("/config/save")
    @ResponseBody
    public AjaxResult configSave(@RequestParam String baseUrl, @RequestParam(required = false) String adminCallbackUrl) {
        if (baseUrl == null) baseUrl = "";
        baseUrl = baseUrl.trim();
        SysConfig cfg = sysConfigService.selectConfigByKeyEntity(CONFIG_KEY_BASE_URL);
        if (cfg != null) {
            cfg.setConfigValue(baseUrl);
            sysConfigService.updateConfig(cfg);
        } else {
            SysConfig newCfg = new SysConfig();
            newCfg.setConfigName("RootSeeker 分析服务地址");
            newCfg.setConfigKey(CONFIG_KEY_BASE_URL);
            newCfg.setConfigValue(baseUrl);
            newCfg.setConfigType("Y");
            newCfg.setCreateBy(getLoginName());
            newCfg.setRemark("RootSeeker 服务 base URL，用于拉取仓库、同步等");
            int row = sysConfigService.insertConfig(newCfg);
            if (row <= 0) return error("保存失败");
        }
        String cb = adminCallbackUrl != null ? adminCallbackUrl.trim() : "";
        SysConfig cbCfg = sysConfigService.selectConfigByKeyEntity(CONFIG_KEY_ADMIN_CALLBACK_URL);
        if (cbCfg != null) {
            cbCfg.setConfigValue(cb);
            sysConfigService.updateConfig(cbCfg);
        } else if (!cb.isEmpty()) {
            SysConfig newCb = new SysConfig();
            newCb.setConfigName("Admin 回调地址");
            newCb.setConfigKey(CONFIG_KEY_ADMIN_CALLBACK_URL);
            newCb.setConfigValue(cb);
            newCb.setConfigType("Y");
            newCb.setCreateBy(getLoginName());
            newCb.setRemark("索引/清除任务完成后 RootSeeker 回调此 URL，如 http://域名/gitsource/index/callback");
            sysConfigService.insertConfig(newCb);
        }
        return success();
    }

    @RequiresPermissions("gitsource:credential:edit")
    @Log(title = "Git凭证", businessType = BusinessType.UPDATE)
    @PostMapping("/credential/save")
    @ResponseBody
    public AjaxResult credentialSave(GitSourceCredential credential) {
        return toAjax(credentialService.saveCredential(credential));
    }

    /** 验证凭证（调用 RootSeeker，不保存） */
    @RequiresPermissions("gitsource:repo:add")
    @PostMapping("/verify")
    @ResponseBody
    public AjaxResult verifyCredentials(@RequestParam String domain, @RequestParam String username, @RequestParam String password, @RequestParam(required = false) String platform) {
        try {
            Map<String, Object> result = rootSeekerClient.verifyCredentials(domain, username, password, platform);
            String status = result != null ? (String) result.get("status") : null;
            String msg = result != null ? (String) result.get("message") : "未知";
            if ("ok".equals(status)) {
                return success(msg);
            }
            return error("验证失败: " + msg);
        } catch (Exception e) {
            return error("验证失败: " + e.getMessage());
        }
    }

    /** 拉取仓库列表（调用 RootSeeker，并同步到管理端 git_source_repos 表供页面展示） */
    @RequiresPermissions("gitsource:repo:add")
    @Log(title = "拉取仓库列表", businessType = BusinessType.OTHER)
    @PostMapping("/fetch")
    @ResponseBody
    public AjaxResult fetchRepos(@RequestParam String domain, @RequestParam String username, @RequestParam String password, @RequestParam(required = false) String platform) {
        try {
            GitSourceCredential cred = new GitSourceCredential();
            cred.setId(1);
            cred.setDomain(domain);
            cred.setUsername(username);
            cred.setPassword(password);
            cred.setPlatform(platform != null && !platform.isEmpty() ? platform : "generic");
            credentialService.saveCredential(cred);
            Map<String, Object> result = rootSeekerClient.connectAndFetchRepos(domain, username, password, platform);
            // 将 RootSeeker 返回的仓库同步到管理端 git_source_repos 表，供仓库管理页面展示
            Object reposObj = result.get("repos");
            if (reposObj instanceof List) {
                @SuppressWarnings("unchecked")
                List<Map<String, Object>> repos = (List<Map<String, Object>>) reposObj;
                Date now = new Date();
                for (Map<String, Object> r : repos) {
                    try {
                        Object idObj = r.get("id");
                        String id = idObj != null ? idObj.toString() : null;
                        Object fnObj = r.get("full_name");
                        String fullName = fnObj != null ? fnObj.toString() : null;
                        Object fpObj = r.get("full_path");
                        String fullPath = fpObj != null ? fpObj.toString() : null;
                        Object pidObj = r.get("platform_id");
                        String platformId = pidObj != null ? pidObj.toString() : null;
                        Object urlObj = r.get("git_url");
                        String gitUrl = urlObj != null ? urlObj.toString() : null;
                        Object dbObj = r.get("default_branch");
                        String defaultBranch = dbObj != null ? dbObj.toString() : "master";
                        if (id == null || id.isEmpty() || fullName == null || fullName.isEmpty() || gitUrl == null || gitUrl.isEmpty())
                            continue;
                        GitSourceRepo repo = repoService.selectRepoById(id);
                        if (repo != null) {
                            repo.setFullName(fullName);
                            repo.setFullPath(fullPath);
                            repo.setPlatformId(platformId);
                            repo.setGitUrl(gitUrl);
                            repo.setDefaultBranch(defaultBranch != null ? defaultBranch : "master");
                            repoService.updateRepo(repo);
                        } else {
                            GitSourceRepo newRepo = new GitSourceRepo();
                            newRepo.setId(id);
                            newRepo.setFullName(fullName);
                            newRepo.setFullPath(fullPath);
                            newRepo.setPlatformId(platformId);
                            newRepo.setGitUrl(gitUrl);
                            newRepo.setDefaultBranch(defaultBranch != null ? defaultBranch : "master");
                            newRepo.setEnabled(0);
                            newRepo.setSelectedBranches("[]");
                            newRepo.setCreatedAt(now);
                            repoService.insertRepo(newRepo);
                        }
                    } catch (Exception ex) {
                        log.error("同步仓库 {} 失败: {}", r.get("id"), ex.getMessage());
                    }
                }
            }
            rootSeekerClient.notifyRepoChanged();
            return AjaxResult.success("拉取成功", result);
        } catch (Exception e) {
            return error("拉取失败: " + e.getMessage());
        }
    }

    /** 同步所有已启用仓库 */
    @RequiresPermissions("gitsource:repo:edit")
    @Log(title = "同步仓库", businessType = BusinessType.OTHER)
    @PostMapping("/sync")
    @ResponseBody
    public AjaxResult syncRepos() {
        try {
            Map<String, Object> result = rootSeekerClient.syncRepos();
            rootSeekerClient.notifyRepoChanged();
            return AjaxResult.success("同步完成", result);
        } catch (Exception e) {
            return error("同步失败: " + e.getMessage());
        }
    }

    // ---------- 索引管理 ----------

    /** 重新同步索引状态：从 RootSeeker 查询实时状态，调用 callback 逻辑写入 repo_index_status */
    @RequiresPermissions("gitsource:repo:list")
    @Log(title = "重新同步索引状态", businessType = BusinessType.OTHER)
    @PostMapping("/index/sync-status")
    @ResponseBody
    public AjaxResult syncIndexStatus() {
        try {
            Map<String, Object> result = rootSeekerClient.getIndexStatus();
            Object reposObj = result != null ? result.get("repos") : null;
            if (!(reposObj instanceof List)) {
                return AjaxResult.success("无仓库数据", java.util.Collections.singletonMap("synced", 0));
            }
            @SuppressWarnings("unchecked")
            List<Map<String, Object>> repos = (List<Map<String, Object>>) reposObj;
            int count = repoIndexStatusService.syncFromRootSeekerStatus(repos);
            return AjaxResult.success("已同步 " + count + " 个仓库的索引状态", java.util.Collections.singletonMap("synced", count));
        } catch (Exception e) {
            return error("同步失败: " + e.getMessage());
        }
    }

    /** 获取各仓库的 Qdrant 与 Zoekt 索引状态（从 repo_index_status 表读取，由 RootSeeker 回调更新） */
    @RequiresPermissions("gitsource:repo:list")
    @GetMapping("/index/status")
    @ResponseBody
    public AjaxResult getIndexStatus() {
        try {
            List<GitSourceRepo> repos = repoService.selectRepoList(new GitSourceRepo());
            List<RepoIndexStatus> statusList = repoIndexStatusService.listAll();
            java.util.Map<String, RepoIndexStatus> statusMap = new java.util.HashMap<>();
            for (RepoIndexStatus s : statusList) {
                if (s.getServiceName() != null) statusMap.put(s.getServiceName(), s);
            }
            List<Map<String, Object>> resultRepos = new java.util.ArrayList<>();
            for (GitSourceRepo r : repos) {
                // service_name 与 RootSeeker 一致：取 full_path/full_name 最后一段，再 replace("/","-")
                // RootSeeker 的 mysql_storage 将 full_name 转为 split("/")[-1]，故需对齐
                String path = StringUtils.isNotEmpty(r.getFullPath()) ? r.getFullPath() : r.getFullName();
                if (path == null) path = r.getId();
                if (path == null || path.isEmpty()) continue;
                String lastPart = path.contains("/") ? path.substring(path.lastIndexOf("/") + 1) : path;
                String sn = lastPart.replace("/", "-");
                if (sn.isEmpty()) continue;
                RepoIndexStatus st = statusMap.get(sn);
                if (st == null) {
                    st = statusMap.get(sn.replace("_", "-"));
                }
                if (st == null) {
                    st = statusMap.get(sn.replace("-", "_"));
                }
                // 兼容：status 可能用 full_path 格式（如 org-api-distribution），再尝试
                if (st == null && path.contains("/")) {
                    String fullSn = path.replace("/", "-");
                    st = statusMap.get(fullSn);
                }
                Map<String, Object> item = new java.util.HashMap<>();
                item.put("service_name", sn);
                item.put("qdrant_status", st != null && st.getQdrantStatus() != null ? st.getQdrantStatus() : "未索引");
                item.put("qdrant_count", st != null && st.getQdrantCount() != null ? st.getQdrantCount() : 0);
                item.put("zoekt_status", st != null && st.getZoektStatus() != null ? st.getZoektStatus() : "未索引");
                resultRepos.add(item);
            }
            Map<String, Object> result = new java.util.HashMap<>();
            result.put("repos", resultRepos);
            return AjaxResult.success(result);
        } catch (Exception e) {
            return error("获取索引状态失败: " + e.getMessage());
        }
    }

    /** RootSeeker 回调：接收索引/清除任务完成通知，放入内存队列 FIFO 异步处理 */
    @Anonymous
    @PostMapping("/index/callback")
    @ResponseBody
    public AjaxResult indexCallback(@RequestBody Map<String, Object> payload) {
        log.info("[IndexCallback] ========== 收到 /gitsource/index/callback 请求 ==========");
        if (payload == null) {
            log.warn("[IndexCallback] payload 为空，忽略");
            return success();
        }
        log.info("[IndexCallback] 回调信息: {}", formatCallbackInfo(payload));
        Object sn = payload.get("service_name");
        Object tt = payload.get("task_type");
        Object st = payload.get("status");
        log.info("[IndexCallback] 入队: service_name={}, task_type={}, status={}", sn, tt, st);
        boolean ok = indexCallbackQueue.offer(payload);
        if (!ok) {
            return error("回调队列已满，请稍后重试");
        }
        return success();
    }

    /** 为指定仓库建向量索引（走队列时立即返回 job_id） */
    @RequiresPermissions("gitsource:repo:edit")
    @Log(title = "索引仓库", businessType = BusinessType.OTHER)
    @PostMapping("/index/repo")
    @ResponseBody
    public AjaxResult indexRepo(@RequestParam String serviceName, @RequestParam(defaultValue = "false") Boolean incremental) {
        try {
            repoIndexStatusService.setStatus(serviceName, "索引中", null);
            Map<String, Object> result = rootSeekerClient.indexRepo(serviceName, Boolean.TRUE.equals(incremental));
            String msg = "queued".equals(result.get("status")) ? "任务已入队，正在排队执行" : "索引完成";
            return AjaxResult.success(msg, result);
        } catch (Exception e) {
            return error("索引失败: " + e.getMessage());
        }
    }

    /** 为指定仓库建 Zoekt 索引（走队列时立即返回 job_id） */
    @RequiresPermissions("gitsource:repo:edit")
    @Log(title = "Zoekt索引", businessType = BusinessType.OTHER)
    @PostMapping("/index/zoekt")
    @ResponseBody
    public AjaxResult indexZoektRepo(@RequestParam String serviceName) {
        try {
            repoIndexStatusService.setStatus(serviceName, null, "索引中");
            Map<String, Object> result = rootSeekerClient.indexZoektRepo(serviceName);
            String msg = "queued".equals(result.get("status")) ? "任务已入队，正在排队执行" : "Zoekt 索引完成";
            return AjaxResult.success(msg, result);
        } catch (Exception e) {
            return error("Zoekt 索引失败: " + e.getMessage());
        }
    }

    /** 获取索引队列列表（供 Admin 队列调度展示） */
    @RequiresPermissions("gitsource:repo:list")
    @GetMapping("/index/queue")
    @ResponseBody
    public AjaxResult getIndexQueue() {
        try {
            Map<String, Object> result = rootSeekerClient.getIndexQueue();
            return AjaxResult.success(result);
        } catch (Exception e) {
            return error("获取队列失败: " + e.getMessage());
        }
    }

    /** 获取索引任务详情（含日志） */
    @RequiresPermissions("gitsource:repo:list")
    @GetMapping("/index/job/{jobId}")
    @ResponseBody
    public AjaxResult getIndexJob(@PathVariable String jobId) {
        try {
            Map<String, Object> result = rootSeekerClient.getIndexJob(jobId);
            return AjaxResult.success(result);
        } catch (Exception e) {
            return error("获取任务详情失败: " + e.getMessage());
        }
    }

    /** 清除指定仓库向量并重新全量索引 */
    @RequiresPermissions("gitsource:repo:edit")
    @Log(title = "重置仓库索引", businessType = BusinessType.OTHER)
    @PostMapping("/index/repo/reset")
    @ResponseBody
    public AjaxResult resetRepoIndex(@RequestParam String serviceName) {
        try {
            repoIndexStatusService.setStatus(serviceName, "索引中", null);
            Map<String, Object> result = rootSeekerClient.resetRepoIndex(serviceName);
            return AjaxResult.success("重置完成", result);
        } catch (Exception e) {
            return error("重置失败: " + e.getMessage());
        }
    }

    /** 重新同步：先清除后添加，添加完成后触发依赖图重建 */
    @RequiresPermissions("gitsource:repo:edit")
    @Log(title = "重新同步仓库", businessType = BusinessType.OTHER)
    @PostMapping("/index/repo/resync")
    @ResponseBody
    public AjaxResult resyncRepoIndex(@RequestParam String serviceName) {
        try {
            repoIndexStatusService.setStatus(serviceName, "索引中", "索引中");
            Map<String, Object> result = rootSeekerClient.resyncRepoIndex(serviceName);
            return AjaxResult.success("已入队处理", result);
        } catch (Exception e) {
            return error("重新同步失败: " + e.getMessage());
        }
    }

    /** 仅清除指定仓库向量 */
    @RequiresPermissions("gitsource:repo:edit")
    @Log(title = "清除仓库索引", businessType = BusinessType.OTHER)
    @PostMapping("/index/repo/clear")
    @ResponseBody
    public AjaxResult clearRepoIndex(@RequestParam String serviceName) {
        try {
            repoIndexStatusService.setStatus(serviceName, "清理中", "清理中");
            Map<String, Object> result = rootSeekerClient.clearRepoIndex(serviceName);
            return AjaxResult.success("已清除", result);
        } catch (Exception e) {
            return error("清除失败: " + e.getMessage());
        }
    }

    /** 清除全部向量，可选重索引（事件入队） */
    @RequiresPermissions("gitsource:repo:edit")
    @Log(title = "全量清除索引", businessType = BusinessType.OTHER)
    @PostMapping("/index/reset-all")
    @ResponseBody
    public AjaxResult resetAllIndex(@RequestParam(defaultValue = "false") Boolean reindex) {
        try {
            Map<String, Object> result = rootSeekerClient.resetAllIndex(Boolean.TRUE.equals(reindex));
            String msg = result != null && result.containsKey("message") ? String.valueOf(result.get("message")) : "操作完成";
            return AjaxResult.success(msg, result);
        } catch (Exception e) {
            return error("操作失败: " + e.getMessage());
        }
    }

    /** 全量重载：同步 + 清除 + 重索引（事件入队） */
    @RequiresPermissions("gitsource:repo:edit")
    @Log(title = "全量重载", businessType = BusinessType.OTHER)
    @PostMapping("/full-reload")
    @ResponseBody
    public AjaxResult fullReloadRepos(@RequestParam(required = false) String serviceName) {
        try {
            Map<String, Object> result = rootSeekerClient.fullReloadRepos(serviceName);
            String msg = result != null && result.containsKey("message") ? String.valueOf(result.get("message")) : "全量重载完成";
            return AjaxResult.success(msg, result);
        } catch (Exception e) {
            return error("全量重载失败: " + e.getMessage());
        }
    }

    // ---------- 异常测试 ----------

    /** 异常测试页面 */
    @RequiresPermissions("gitsource:repo:view")
    @GetMapping("/ingestTest")
    public String ingestTest() {
        return prefix + "/ingestTest";
    }

    /**
     * 获取仓库列表供下拉选择。mode=config 从 RootSeeker 获取（config+git_source），mode=mysql 从本地 git_source_repos 表获取。
     */
    @RequiresPermissions("gitsource:repo:list")
    @GetMapping("/ingestTest/repos")
    @ResponseBody
    public AjaxResult getIngestTestRepos(@RequestParam(defaultValue = "config") String mode) {
        try {
            Map<String, Object> data = new java.util.HashMap<>();
            if ("mysql".equalsIgnoreCase(mode)) {
                GitSourceRepo query = new GitSourceRepo();
                query.setEnabled(1);
                List<GitSourceRepo> list = repoService.selectRepoList(query);
                List<Map<String, String>> out = new java.util.ArrayList<>();
                for (GitSourceRepo r : list) {
                    String sn = (r.getFullName() != null ? r.getFullName() : "").replace("/", "-");
                    if (!sn.isEmpty()) {
                        Map<String, String> m = new java.util.HashMap<>();
                        m.put("service_name", sn);
                        m.put("fullName", r.getFullName());
                        m.put("repo_id", r.getId());
                        out.add(m);
                    }
                }
                data.put("repos", out);
            } else {
                Map<String, Object> result = rootSeekerClient.getReposList();
                Object repos = result != null ? result.get("repos") : null;
                data.put("repos", repos != null ? repos : Collections.emptyList());
            }
            return AjaxResult.success(data);
        } catch (Exception e) {
            return error("获取仓库列表失败: " + e.getMessage());
        }
    }

    /** 提交异常测试：调用 RootSeeker POST /ingest，可选传 repo_id 实现日志与仓库关联 */
    @RequiresPermissions("gitsource:repo:edit")
    @Log(title = "异常测试", businessType = BusinessType.OTHER)
    @PostMapping("/ingestTest/submit")
    @ResponseBody
    public AjaxResult ingestTestSubmit(
            @RequestParam String serviceName,
            @RequestParam String errorLog,
            @RequestParam(defaultValue = "default_error_context") String queryKey,
            @RequestParam(required = false) String repoId) {
        if (StringUtils.isEmpty(serviceName) || StringUtils.isEmpty(errorLog)) {
            return error("服务名和错误日志不能为空");
        }
        try {
            Map<String, Object> event = new java.util.HashMap<>();
            event.put("service_name", serviceName);
            event.put("error_log", errorLog);
            event.put("query_key", queryKey != null ? queryKey : "default_error_context");
            if (StringUtils.isNotEmpty(repoId)) {
                event.put("repo_id", repoId);
            }
            Map<String, Object> result = rootSeekerClient.ingest(event);
            return AjaxResult.success("已提交，分析任务已入队", result);
        } catch (Exception e) {
            return error("提交失败: " + e.getMessage());
        }
    }

    /** 查询分析结果：根据 analysis_id 调用 RootSeeker GET /analysis/{analysis_id} */
    @RequiresPermissions("gitsource:repo:list")
    @GetMapping("/ingestTest/result")
    @ResponseBody
    public AjaxResult getIngestTestResult(@RequestParam String analysisId) {
        if (StringUtils.isEmpty(analysisId)) {
            return error("任务ID不能为空");
        }
        try {
            Map<String, Object> result = rootSeekerClient.getAnalysis(analysisId.trim());
            return AjaxResult.success(result);
        } catch (Exception e) {
            return error("查询失败: " + e.getMessage());
        }
    }

    private static String formatCallbackInfo(Map<String, Object> payload) {
        if (payload == null) return "null";
        StringBuilder sb = new StringBuilder();
        for (Map.Entry<String, Object> e : payload.entrySet()) {
            if (sb.length() > 0) sb.append(", ");
            sb.append(e.getKey()).append("=").append(e.getValue());
        }
        return sb.toString();
    }

}
