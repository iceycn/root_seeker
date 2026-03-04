package com.ruoyi.web.config;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

@Component
@ConfigurationProperties(prefix = "root-seeker")
public class RootSeekerConfig {
    private String baseUrl = "http://localhost:8000";
    private String apiKey = "";
    private String adminCallbackUrl = "";

    public String getBaseUrl() { return baseUrl; }
    public void setBaseUrl(String baseUrl) { this.baseUrl = baseUrl; }
    public String getApiKey() { return apiKey; }
    public void setApiKey(String apiKey) { this.apiKey = apiKey; }
    public String getAdminCallbackUrl() { return adminCallbackUrl; }
    public void setAdminCallbackUrl(String adminCallbackUrl) { this.adminCallbackUrl = adminCallbackUrl; }
}
