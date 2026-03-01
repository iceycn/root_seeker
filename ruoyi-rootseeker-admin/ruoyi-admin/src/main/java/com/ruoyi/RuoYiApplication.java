package com.ruoyi;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.autoconfigure.jdbc.DataSourceAutoConfiguration;

/**
 * 启动程序
 * 
 * @author ruoyi
 */
@SpringBootApplication(exclude = { DataSourceAutoConfiguration.class })
public class RuoYiApplication
{
    public static void main(String[] args)
    {
        // System.setProperty("spring.devtools.restart.enabled", "false");
        SpringApplication.run(RuoYiApplication.class, args);
        System.out.println("(♥◠‿◠)ﾉﾞ  RootSeeker 管理端启动成功   ლ(´ڡ`ლ)ﾞ  \n" +
                "  ____            _   _____            _    \n" +
                " |  _ \\ ___  ___| |_| ____| ___  ___| | __ \n" +
                " | |_) / _ \\/ __| __|  _| |/ _ \\/ __| |/ / \n" +
                " |  _ <  __/ (__| |_| |___|  __/ (__|   <  \n" +
                " |_| \\_\\___|\\___|\\__|_____|\\___|\\___|_|\\_\\");
    }
}