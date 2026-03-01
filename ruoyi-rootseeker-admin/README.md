<p align="center">
	<img alt="logo" src="https://oscimg.oschina.net/oscnet/up-dd77653d7c9f197dd9d93684f3c8dcfbab6.png">
</p>
<h1 align="center" style="margin: 30px 0 30px; font-weight: bold;">RootSeeker 管理端</h1>
<h4 align="center">RootSeeker 管理后台，用于 Git 仓库与 AI 应用配置管理</h4>
<p align="center">
	<a href="https://img.shields.io/badge/license-MIT-blue.svg"><img src="https://img.shields.io/github/license/mashape/apistatus.svg"></a>
</p>

## 平台简介

RootSeeker 管理端用于管理 Git 仓库、AI 应用配置，与 RootSeeker 分析服务协同工作。项目地址：<https://gitee.com/icey_1/root_seeker>支持仓库拉取、同步、分支配置，以及 LLM、Embedding、Qdrant 等 AI 日志分析相关配置。

* 前端基于 [Hplus(H+)](https://gitee.com/hplus_admin/hplus) 后台主题 UI 框架。

## 内置功能

1.  用户管理：用户是系统操作者，该功能主要完成系统用户配置。
2.  部门管理：配置系统组织机构（公司、部门、小组），树结构展现支持数据权限。
3.  岗位管理：配置系统用户所属担任职务。
4.  菜单管理：配置系统菜单，操作权限，按钮权限标识等。
5.  角色管理：角色菜单权限分配、设置角色按机构进行数据范围权限划分。
6.  字典管理：对系统中经常使用的一些较为固定的数据进行维护。
7.  参数管理：对系统动态配置常用参数。
8.  通知公告：系统通知公告信息发布维护。
9.  操作日志：系统正常操作日志记录和查询；系统异常信息日志记录和查询。
10. 登录日志：系统登录日志记录查询包含登录异常。
11. 在线用户：当前系统中活跃用户状态监控。
12. 定时任务：在线（添加、修改、删除)任务调度包含执行结果日志。
13. 代码生成：前后端代码的生成（java、html、xml、sql）支持CRUD下载 。
14. 系统接口：根据业务代码自动生成相关的api接口文档。
15. 服务监控：监视当前系统CPU、内存、磁盘、堆栈等相关信息。
16. 缓存监控：对系统的缓存查询，删除、清空等操作。
17. 在线构建器：拖动表单元素生成相应的HTML代码。
18. 连接池监视：监视当前系统数据库连接池状态，可进行分析SQL找出系统性能瓶颈。

## 在线体验

- 默认账号：admin / admin123

## 演示图

<table>
    <tr>
        <td><img src="https://oscimg.oschina.net/oscnet/up-42e518aa72a24d228427a1261cb3679f395.png"/></td>
        <td><img src="https://oscimg.oschina.net/oscnet/up-7f20dd0edba25e5187c5c4dd3ec7d3d9797.png"/></td>
    </tr>
    <tr>
        <td><img src="https://oscimg.oschina.net/oscnet/up-2dae3d87f6a8ca05057db059cd9a411d51d.png"/></td>
        <td><img src="https://oscimg.oschina.net/oscnet/up-ea4d98423471e55fba784694e45d12bd4bb.png"/></td>
    </tr>
    <tr>
        <td><img src="https://oscimg.oschina.net/oscnet/up-7f6c6e9f5873efca09bd2870ee8468b8fce.png"/></td>
        <td><img src="https://oscimg.oschina.net/oscnet/up-c708b65f2c382a03f69fe1efa8d341e6cff.png"/></td>
    </tr>
	<tr>
        <td><img src="https://oscimg.oschina.net/oscnet/up-9ab586c47dd5c7b92bca0d727962c90e3b8.png"/></td>
        <td><img src="https://oscimg.oschina.net/oscnet/up-ef954122a2080e02013112db21754b955c6.png"/></td>
    </tr>	 
    <tr>
        <td><img src="https://oscimg.oschina.net/oscnet/up-088edb4d531e122415a1e2342bccb1a9691.png"/></td>
        <td><img src="https://oscimg.oschina.net/oscnet/up-f886fe19bd820c0efae82f680223cac196c.png"/></td>
    </tr>
	<tr>
        <td><img src="https://oscimg.oschina.net/oscnet/up-c7a2eb71fa65d6e660294b4bccca613d638.png"/></td>
        <td><img src="https://oscimg.oschina.net/oscnet/up-e60137fb0787defe613bd83331dc4755a70.png"/></td>
    </tr>
	<tr>
        <td><img src="https://oscimg.oschina.net/oscnet/up-7c51c1b5758f0a0f92ed3c60469b7526f9f.png"/></td>
        <td><img src="https://oscimg.oschina.net/oscnet/up-15181aed45bb2461aa97b594cbf2f86ea5f.png"/></td>
    </tr>
	<tr>
        <td><img src="https://oscimg.oschina.net/oscnet/up-83326ad52ea63f67233d126226738054d98.png"/></td>
        <td><img src="https://oscimg.oschina.net/oscnet/up-3bd6d31e913b70df00107db51d64ef81df7.png"/></td>
    </tr>
	<tr>
        <td><img src="https://oscimg.oschina.net/oscnet/up-70a2225836bc82042a6785edf6299e2586a.png"/></td>
        <td><img src="https://oscimg.oschina.net/oscnet/up-0184d6ab01fdc6667a14327fcaf8b46345d.png"/></td>
    </tr>
	<tr>
        <td><img src="https://oscimg.oschina.net/oscnet/up-64d8086dc2c02c8f71170290482f7640098.png"/></td>
        <td><img src="https://oscimg.oschina.net/oscnet/up-5e4daac0bb59612c5038448acbcef235e3a.png"/></td>
    </tr>
</table>


## 交流群

QQ群： [![加入QQ群](https://img.shields.io/badge/已满-1389287-blue.svg)](https://jq.qq.com/?_wv=1027&k=5HBAaYN)  [![加入QQ群](https://img.shields.io/badge/已满-1679294-blue.svg)](https://jq.qq.com/?_wv=1027&k=5cHeRVW)  [![加入QQ群](https://img.shields.io/badge/已满-1529866-blue.svg)](https://jq.qq.com/?_wv=1027&k=53R0L5Z)  [![加入QQ群](https://img.shields.io/badge/已满-1772718-blue.svg)](https://jq.qq.com/?_wv=1027&k=5g75dCU)  [![加入QQ群](https://img.shields.io/badge/已满-1366522-blue.svg)](https://jq.qq.com/?_wv=1027&k=58cPoHA)  [![加入QQ群](https://img.shields.io/badge/已满-1382251-blue.svg)](https://jq.qq.com/?_wv=1027&k=5Ofd4Pb)  [![加入QQ群](https://img.shields.io/badge/已满-1145125-blue.svg)](https://jq.qq.com/?_wv=1027&k=5yugASz)  [![加入QQ群](https://img.shields.io/badge/已满-86752435-blue.svg)](https://jq.qq.com/?_wv=1027&k=5Rf3d2P)  [![加入QQ群](https://img.shields.io/badge/已满-134072510-blue.svg)](https://jq.qq.com/?_wv=1027&k=5ZIjaeP)  [![加入QQ群](https://img.shields.io/badge/已满-210336300-blue.svg)](https://jq.qq.com/?_wv=1027&k=5CJw1jY)  [![加入QQ群](https://img.shields.io/badge/已满-339522636-blue.svg)](https://jq.qq.com/?_wv=1027&k=5omzbKc)  [![加入QQ群](https://img.shields.io/badge/已满-130035985-blue.svg)](https://jq.qq.com/?_wv=1027&k=qPIKBb7s)  [![加入QQ群](https://img.shields.io/badge/已满-143151071-blue.svg)](https://jq.qq.com/?_wv=1027&k=4NsjKbtU)  [![加入QQ群](https://img.shields.io/badge/已满-158781320-blue.svg)](https://jq.qq.com/?_wv=1027&k=VD2pkz2G)  [![加入QQ群](https://img.shields.io/badge/已满-201531282-blue.svg)](https://jq.qq.com/?_wv=1027&k=HlshFwkJ)  [![加入QQ群](https://img.shields.io/badge/已满-101526938-blue.svg)](https://jq.qq.com/?_wv=1027&k=0ARRrO9V)  [![加入QQ群](https://img.shields.io/badge/已满-264355400-blue.svg)](https://jq.qq.com/?_wv=1027&k=up9k3ZXJ)  [![加入QQ群](https://img.shields.io/badge/已满-298522656-blue.svg)](https://jq.qq.com/?_wv=1027&k=540WfdEr)  [![加入QQ群](https://img.shields.io/badge/已满-139845794-blue.svg)](https://jq.qq.com/?_wv=1027&k=ss91fC4t)  [![加入QQ群](https://img.shields.io/badge/已满-185760789-blue.svg)](https://jq.qq.com/?_wv=1027&k=Cqd66IKe) [![加入QQ群](https://img.shields.io/badge/已满-175104288-blue.svg)](https://jq.qq.com/?_wv=1027&k=7FplYUnR) [![加入QQ群](https://img.shields.io/badge/已满-174942938-blue.svg)](http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=lqMHu_5Fskm7H2S1vNAQTtzAUokVydwc&authKey=ptw0Fpch5pbNocML3CIJKKqZBaq2DI7cusKuzIgfMNiY3t9Pvd9hP%2BA8WYx3yaY1&noverify=0&group_code=174942938) [![加入QQ群](https://img.shields.io/badge/已满-287843737-blue.svg)](http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=blYlRDmwZXSXI5pVrPPU7ZJ1stFJ6Q2Q&authKey=ForGBWffHVlPt9NE3d7g4DoOIouBh%2BqvAj2lp1CLReHfZAUaK7SRrdwsChKpRJDJ&noverify=0&group_code=287843737) [![加入QQ群](https://img.shields.io/badge/已满-232896766-blue.svg)](http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=KTVAIhggR3rR3uZWK9A8kR4yYNREQ4jo&authKey=An4DUV9e7uK8I8VgBbp949z0ypQoDrOoqvVg%2FWOr2vuNNDMZUAMPvqHor6TFMIgz&noverify=0&group_code=232896766) [![加入QQ群](https://img.shields.io/badge/已满-180208928-blue.svg)](http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=XwhV8deuZXt__yteR1clNanVSXzA-ugq&authKey=ezgwKqEZPdP%2FgC9I03OBkJb%2Biii8yvVfwrcQuu0%2FL6ILXcRdHYDBFKCXeoeBT0E6&noverify=0&group_code=180208928) [![加入QQ群](https://img.shields.io/badge/140284548-blue.svg)](http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=WqsGDxpGkqOPeWGOf3I32f_rXxdhqYNr&authKey=kvdF5df7PO9bzWxmixKhZN6ShsECBiuGUmmzTZBWVr2MVOfJ8%2F4oD0Gws0rbgYfz&noverify=0&group_code=140284548)