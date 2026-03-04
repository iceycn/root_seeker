package com.ruoyi.web.component;

import java.util.Map;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.LinkedBlockingQueue;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/**
 * 索引回调内存队列，FIFO 顺序处理。
 * RootSeeker 回调入队后立即返回，由后台消费者异步处理。
 */
@Component
public class IndexCallbackQueue {
    private static final Logger log = LoggerFactory.getLogger(IndexCallbackQueue.class);
    private static final int DEFAULT_CAPACITY = 10000;

    private final BlockingQueue<Map<String, Object>> queue = new LinkedBlockingQueue<>(DEFAULT_CAPACITY);

    /**
     * 将回调 payload 放入队列，FIFO。
     *
     * @param payload 回调数据
     * @return true 入队成功，false 队列已满
     */
    public boolean offer(Map<String, Object> payload) {
        boolean ok = queue.offer(payload);
        if (!ok) {
            log.warn("[IndexCallbackQueue] 队列已满，丢弃回调 service_name={}", payload != null ? payload.get("service_name") : "?");
        }
        return ok;
    }

    /**
     * 阻塞取出队首元素，供消费者使用。
     */
    public Map<String, Object> take() throws InterruptedException {
        return queue.take();
    }

    /**
     * 当前队列长度。
     */
    public int size() {
        return queue.size();
    }
}
