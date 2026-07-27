# 舞镜 · WuJing

AI舞蹈评分系统。上传舞蹈视频，AI逐帧对比评分、纠错、生成练习计划。

## 访问

- GitHub Pages: https://karentan30.github.io/wujing-app/
- Vercel: https://wj-clean.vercel.app

## 功能

- 登录/注册（邮箱+密码）
- 上传舞蹈视频（MP4/MOV，最大500MB）
- 选参考老师（月 / 月·圆舞 / 成魔）
- AI四维评分（节拍/延展/镜像/情感）
- 问题检测+改进建议
- 5天练习计划

## 技术栈

- 纯HTML/CSS/JS无框架
- MediaPipe姿态分析引擎
- FastAPI后端（HK服务器）
- SQLite数据库

## 开发

```bash
git clone https://github.com/karentan30/wujing-app.git
cd wujing-app
# 直接打开 index.html 即可本地预览
# API请求指向 https://wujing.mylumee.cn/api/
```
