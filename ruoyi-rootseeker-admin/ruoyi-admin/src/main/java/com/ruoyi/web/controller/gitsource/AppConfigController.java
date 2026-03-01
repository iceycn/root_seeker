package com.ruoyi.web.controller.gitsource;

import java.util.Map;
import org.apache.shiro.authz.annotation.RequiresPermissions;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Controller;
import org.springframework.ui.ModelMap;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseBody;
import com.ruoyi.common.annotation.Log;
import com.ruoyi.common.core.controller.BaseController;
import com.ruoyi.common.core.domain.AjaxResult;
import com.ruoyi.common.enums.BusinessType;
import com.ruoyi.common.utils.StringUtils;
import com.ruoyi.web.service.RootSeekerClient;

/**
 * RootSeeker 应用配置（AI 日志分析：LLM、Embedding、Qdrant 等）
 * 支持 file / database 双模式，通过 RootSeeker /app-config API 读写
 */
@Controller
@RequestMapping("/gitsource/appconfig")
public class AppConfigController extends BaseController {
    private static final Logger log = LoggerFactory.getLogger(AppConfigController.class);
    private static final String PREFIX = "gitsource/appconfig";

    @Autowired
    private RootSeekerClient rootSeekerClient;

    @RequiresPermissions("gitsource:config:view")
    @GetMapping
    public String index(ModelMap mmap) {
        return PREFIX + "/config";
    }

    /** 获取全部配置 */
    @RequiresPermissions("gitsource:config:view")
    @PostMapping("/list")
    @ResponseBody
    public AjaxResult list() {
        try {
            Map<String, Object> result = rootSeekerClient.appConfigList();
            return success(result);
        } catch (Exception e) {
            log.error("获取应用配置失败", e);
            return error("获取失败: " + e.getMessage() + "（请确认 RootSeeker 已配置 config_db）");
        }
    }

    /** 获取配置来源 */
    @RequiresPermissions("gitsource:config:view")
    @PostMapping("/source")
    @ResponseBody
    public AjaxResult getSource() {
        try {
            Map<String, Object> result = rootSeekerClient.getConfigSource();
            return success(result);
        } catch (Exception e) {
            log.error("获取配置来源失败", e);
            return error("获取失败: " + e.getMessage());
        }
    }

    /** 设置配置来源 */
    @RequiresPermissions("gitsource:config:edit")
    @Log(title = "AI应用配置", businessType = BusinessType.UPDATE)
    @PostMapping("/source/save")
    @ResponseBody
    public AjaxResult saveSource(@RequestParam String configSource) {
        if (StringUtils.isEmpty(configSource)) {
            return error("配置来源不能为空");
        }
        String src = configSource.trim().toLowerCase();
        if (!"file".equals(src) && !"database".equals(src)) {
            return error("配置来源必须为 file 或 database");
        }
        try {
            rootSeekerClient.setConfigSource(src);
            rootSeekerClient.notifyConfigChanged();
            return success();
        } catch (Exception e) {
            log.error("设置配置来源失败", e);
            return error("设置失败: " + e.getMessage());
        }
    }

    /** 获取指定分类配置 */
    @RequiresPermissions("gitsource:config:view")
    @PostMapping("/category")
    @ResponseBody
    public AjaxResult getCategory(@RequestParam String category) {
        if (StringUtils.isEmpty(category) || !category.matches("[a-zA-Z0-9_-]+")) {
            return error("无效的分类");
        }
        try {
            Map<String, Object> result = rootSeekerClient.getConfigCategory(category);
            return success(result);
        } catch (Exception e) {
            log.error("获取分类配置失败: {}", category, e);
            return error("获取失败: " + e.getMessage());
        }
    }

    /** 保存指定分类配置 */
    @RequiresPermissions("gitsource:config:edit")
    @Log(title = "AI应用配置", businessType = BusinessType.UPDATE)
    @PostMapping("/category/save")
    @ResponseBody
    public AjaxResult saveCategory(@RequestParam String category, @RequestBody Map<String, Object> config) {
        if (StringUtils.isEmpty(category) || !category.matches("[a-zA-Z0-9_-]+")) {
            return error("无效的分类");
        }
        if ("system".equals(category)) {
            return error("系统配置请使用配置来源切换");
        }
        try {
            rootSeekerClient.saveConfigCategory(category, config != null ? config : Map.of());
            rootSeekerClient.notifyConfigChanged();
            return success();
        } catch (Exception e) {
            log.error("保存分类配置失败: {}", category, e);
            return error("保存失败: " + e.getMessage());
        }
    }
}
