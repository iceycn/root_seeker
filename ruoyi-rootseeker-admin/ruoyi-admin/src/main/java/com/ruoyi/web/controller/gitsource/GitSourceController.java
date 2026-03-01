package com.ruoyi.web.controller.gitsource;

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
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseBody;
import com.ruoyi.common.annotation.Log;
import com.ruoyi.common.core.controller.BaseController;
import com.ruoyi.common.core.domain.AjaxResult;
import com.ruoyi.common.core.page.TableDataInfo;
import com.ruoyi.common.enums.BusinessType;
import com.ruoyi.common.utils.StringUtils;
import com.ruoyi.system.domain.GitSourceCredential;
import com.ruoyi.system.domain.GitSourceRepo;
import com.ruoyi.system.domain.SysConfig;
import com.ruoyi.system.service.IGitSourceCredentialService;
import com.ruoyi.system.service.IGitSourceRepoService;
import com.ruoyi.system.service.ISysConfigService;
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

    @Autowired
    private IGitSourceRepoService repoService;
    @Autowired
    private IGitSourceCredentialService credentialService;
    @Autowired
    private ISysConfigService sysConfigService;
    @Autowired
    private RootSeekerClient rootSeekerClient;

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
        repo.setEnabled(enabled != null && enabled ? 1 : 0);
        if (StringUtils.isNotEmpty(branchesStr)) {
            String[] arr = branchesStr.trim().split("\\s*,\\s*");
            String json = arr.length > 0 ? "[\"" + String.join("\",\"", arr) + "\"]" : "[]";
            repo.setSelectedBranches(json);
        }
        int rows = repoService.updateRepo(repo);
        if (rows > 0) {
            try {
                List<String> branches = branchesStr != null && !branchesStr.isEmpty()
                    ? List.of(branchesStr.trim().split("\\s*,\\s*"))
                    : List.of(repo.getDefaultBranch() != null ? repo.getDefaultBranch() : "main");
                rootSeekerClient.configureRepo(repo.getId(), branches, repo.getEnabled() == 1);
                rootSeekerClient.notifyRepoChanged();
            } catch (Exception e) {
                return error("本地已更新，但同步到 RootSeeker 失败: " + e.getMessage());
            }
        }
        return toAjax(rows);
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
        return prefix + "/config";
    }

    @RequiresPermissions("gitsource:config:edit")
    @Log(title = "RootSeeker配置", businessType = BusinessType.UPDATE)
    @PostMapping("/config/save")
    @ResponseBody
    public AjaxResult configSave(@RequestParam String baseUrl) {
        if (baseUrl == null) {
            baseUrl = "";
        }
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
            if (row <= 0) {
                return error("保存失败");
            }
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

    /** 获取各仓库的 Qdrant 与 Zoekt 索引状态 */
    @RequiresPermissions("gitsource:repo:list")
    @GetMapping("/index/status")
    @ResponseBody
    public AjaxResult getIndexStatus() {
        try {
            Map<String, Object> result = rootSeekerClient.getIndexStatus();
            return AjaxResult.success(result);
        } catch (Exception e) {
            return error("获取索引状态失败: " + e.getMessage());
        }
    }

    /** 为指定仓库建向量索引 */
    @RequiresPermissions("gitsource:repo:edit")
    @Log(title = "索引仓库", businessType = BusinessType.OTHER)
    @PostMapping("/index/repo")
    @ResponseBody
    public AjaxResult indexRepo(@RequestParam String serviceName, @RequestParam(defaultValue = "false") Boolean incremental) {
        try {
            Map<String, Object> result = rootSeekerClient.indexRepo(serviceName, Boolean.TRUE.equals(incremental));
            return AjaxResult.success("索引完成", result);
        } catch (Exception e) {
            return error("索引失败: " + e.getMessage());
        }
    }

    /** 清除指定仓库向量并重新全量索引 */
    @RequiresPermissions("gitsource:repo:edit")
    @Log(title = "重置仓库索引", businessType = BusinessType.OTHER)
    @PostMapping("/index/repo/reset")
    @ResponseBody
    public AjaxResult resetRepoIndex(@RequestParam String serviceName) {
        try {
            Map<String, Object> result = rootSeekerClient.resetRepoIndex(serviceName);
            return AjaxResult.success("重置完成", result);
        } catch (Exception e) {
            return error("重置失败: " + e.getMessage());
        }
    }

    /** 仅清除指定仓库向量 */
    @RequiresPermissions("gitsource:repo:edit")
    @Log(title = "清除仓库索引", businessType = BusinessType.OTHER)
    @PostMapping("/index/repo/clear")
    @ResponseBody
    public AjaxResult clearRepoIndex(@RequestParam String serviceName) {
        try {
            Map<String, Object> result = rootSeekerClient.clearRepoIndex(serviceName);
            return AjaxResult.success("已清除", result);
        } catch (Exception e) {
            return error("清除失败: " + e.getMessage());
        }
    }

    /** 清除全部向量，可选重索引 */
    @RequiresPermissions("gitsource:repo:edit")
    @Log(title = "全量清除索引", businessType = BusinessType.OTHER)
    @PostMapping("/index/reset-all")
    @ResponseBody
    public AjaxResult resetAllIndex(@RequestParam(defaultValue = "false") Boolean reindex) {
        try {
            Map<String, Object> result = rootSeekerClient.resetAllIndex(Boolean.TRUE.equals(reindex));
            return AjaxResult.success("操作完成", result);
        } catch (Exception e) {
            return error("操作失败: " + e.getMessage());
        }
    }

    /** 全量重载：同步 + 清除 + 重索引 */
    @RequiresPermissions("gitsource:repo:edit")
    @Log(title = "全量重载", businessType = BusinessType.OTHER)
    @PostMapping("/full-reload")
    @ResponseBody
    public AjaxResult fullReloadRepos(@RequestParam(required = false) String serviceName) {
        try {
            Map<String, Object> result = rootSeekerClient.fullReloadRepos(serviceName);
            return AjaxResult.success("全量重载完成", result);
        } catch (Exception e) {
            return error("全量重载失败: " + e.getMessage());
        }
    }
}
