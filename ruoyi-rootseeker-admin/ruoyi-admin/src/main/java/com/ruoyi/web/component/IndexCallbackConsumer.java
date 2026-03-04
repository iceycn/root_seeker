package com.ruoyi.web.component;

import javax.annotation.PostConstruct;
import javax.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;
import com.ruoyi.system.service.IRepoIndexStatusService;

/**
 * 索引回调队列消费者，单线程 FIFO 处理。
 */
@Component
public class IndexCallbackConsumer {
    private static final Logger log = LoggerFactory.getLogger(IndexCallbackConsumer.class);

    @Autowired
    private IndexCallbackQueue queue;
    @Autowired
    private IRepoIndexStatusService repoIndexStatusService;

    private volatile boolean running = true;
    private Thread consumerThread;

    @PostConstruct
    public void start() {
        consumerThread = new Thread(this::run, "index-callback-consumer");
        consumerThread.setDaemon(false);
        consumerThread.start();
        log.info("[IndexCallbackConsumer] 消费者线程已启动");
    }

    @PreDestroy
    public void stop() {
        running = false;
        if (consumerThread != null) {
            consumerThread.interrupt();
        }
    }

    private void run() {
        while (running) {
            try {
                java.util.Map<String, Object> payload = queue.take();
                if (payload == null) continue;
                log.info("[IndexCallbackConsumer] 从队列取出回调: {}", formatPayload(payload));
                try {
                    repoIndexStatusService.updateFromCallback(payload);
                } catch (Exception e) {
                    log.warn("[IndexCallbackConsumer] 处理回调失败: {}", e.getMessage());
                }
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                break;
            }
        }
        log.info("[IndexCallbackConsumer] 消费者线程已退出");
    }

    private static String formatPayload(java.util.Map<String, Object> payload) {
        if (payload == null) return "null";
        StringBuilder sb = new StringBuilder();
        for (java.util.Map.Entry<String, Object> e : payload.entrySet()) {
            if (sb.length() > 0) sb.append(", ");
            sb.append(e.getKey()).append("=").append(e.getValue());
        }
        return sb.toString();
    }
}
