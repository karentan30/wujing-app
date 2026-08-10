# 舞镜K-pop舞蹈教程库 - 部署指南

## 生成完成状态

- **总文件数**: 21个 HTML
- **总体积**: 252KB
- **创建日期**: 2024-08-10
- **部署位置**: `/Users/karen/projects/舞镜/_live/dance/`

## 文件清单

### 索引页 (1个)
- `index.html` - 完整舞蹈目录，支持搜索和分类筛选

### 单页教程 (20个)

**女团 (8个)**
- `blackpink-lovesick-girls.html`
- `newjeans-hype-boy.html`
- `ive-love-dive.html`
- `aespa-supernova.html`
- `twice-fancy.html`
- `lesserafim-antifragile.html`
- `stayc-bubble.html`
- `kep1er-wa-da-da.html`

**男团 (7个)**
- `bts-butter.html`
- `bts-dynamite.html`
- `enhypen-given-taken.html`
- `txt-0x1lovesong.html`
- `exo-growl.html`
- `got7-not-by-the-moon.html`
- `shinee-ring-ding-dong.html`

**女团其他 (5个)**
- `nmixx-o-o.html`
- `itzy-dalla-dalla.html`
- `mamamoo-hip.html`
- `kara-mister.html`
- `sistar-touch-my-body.html`

## 部署步骤

### 1. 服务器上传
```bash
# 连接HK服务器
ssh -i ~/.ssh/wujing root@47.242.80.65

# 创建目录
mkdir -p /var/www/wujing/_live/dance

# 上传文件 (本地执行)
scp -r /Users/karen/projects/舞镜/_live/dance/ -i ~/.ssh/wujing root@47.242.80.65:/var/www/wujing/_live/
```

### 2. Caddy配置
```
# /etc/caddy/Caddyfile 添加以下行
wujing.mylumee.app/dance/* {
    file_server browse
    root /var/www/wujing/_live/dance
    rewrite * {http.request.uri.path}
}
```

重启Caddy:
```bash
systemctl restart caddy
```

### 3. robots.txt更新
在 `/var/www/wujing/robots.txt` 添加:
```
Allow: /dance/
Sitemap: https://wujing.mylumee.app/dance/sitemap.xml
```

### 4. sitemap.xml生成
创建 `/var/www/wujing/_live/dance/sitemap.xml`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://wujing.mylumee.app/dance/</loc>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>https://wujing.mylumee.app/dance/blackpink-lovesick-girls.html</loc>
    <changefreq>monthly</changefreq>
    <priority>0.8</priority>
  </url>
  <!-- ... 重复20个舞蹈页 ... -->
</urlset>
```

### 5. Google Search Console提交
1. 登录 Google Search Console
2. 添加属性: `https://wujing.mylumee.app/dance/`
3. 验证所有权 (HTML标签或DNS)
4. 提交 sitemap.xml
5. 提交单个页面URL抓取

### 6. Bing Webmaster提交
1. 登录 Bing Webmaster Tools
2. 添加网站: `https://wujing.mylumee.app/`
3. 提交 sitemap.xml
4. 配置抓取频率

### 7. 分析配置
在所有页面 `<head>` 末尾添加:
```html
<!-- Google Analytics -->
<script async src="https://www.googletagmanager.com/gtag/js?id=GA_ID"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());
  gtag('config', 'GA_ID');
</script>

<!-- Conversion Tracking -->
<script>
  document.querySelectorAll('.upload-btn, .cta-button').forEach(btn => {
    btn.addEventListener('click', () => {
      gtag('event', 'dance_tutorial_to_ai', {
        'event_category': 'engagement',
        'event_label': window.location.pathname
      });
    });
  });
</script>
```

## 验证清单

- [ ] 所有21个文件上传成功
- [ ] https://wujing.mylumee.app/dance/ 可访问
- [ ] index.html 搜索功能正常
- [ ] 所有舞蹈页面链接有效
- [ ] robots.txt 已更新
- [ ] sitemap.xml 已生成
- [ ] Google Search Console 已提交
- [ ] 分析代码已部署
- [ ] 移动端响应式正常
- [ ] CTA按钮跳转正确

## SEO验证工具

- Google Search Console: https://search.google.com/search-console
- Google PageSpeed: https://pagespeed.web.dev/
- Google Structured Data Test: https://schema.org/docs/gs.html
- Bing SEO Analyzer: https://www.bingwebmaster.com/

## 监控指标

### 短期 (1-3月)
- 目标排名: 长尾词 3-10 名
- 目标转化: 100-500 用户/月
- 目标停留时间: 2-3 分钟

### 中期 (3-6月)
- 目标排名: 品牌词 1-5 名
- 目标转化: 500-2000 用户/月
- 目标CTR: 内部链接 30-40%

### 长期 (6-12月)
- 目标排名: 高权重关键词首页
- 目标转化: 5000+ 用户/月
- 目标转化率: 8-12% 到AI平台
- 目标停留: 3-5 分钟

## 常见问题

### Q: 如何更新某个舞蹈页?
A: 直接编辑对应的HTML文件,保存后Caddy会自动提供最新版本。

### Q: 如何添加新舞蹈?
A: 
1. 复制任一舞蹈页模板
2. 更新 title, meta, 舞蹈名, 艺人, 核心动作等
3. 在 index.html 的 `dances` 数组中添加新条目
4. 上传到服务器

### Q: 为什么搜索不生效?
A: index.html 使用客户端JavaScript搜索,需要确保JavaScript启用。也可添加服务端搜索API。

### Q: 如何追踪转化?
A: 使用Google Analytics观看 `dance_tutorial_to_ai` 事件,显示用户从教程页跳到AI平台的行为。

## 联系方式

- 舞镜官网: https://wujing.mylumee.app/
- 部署问题: Karen (tan42204@gmail.com)

---
生成于 2024-08-10 | 版本 1.0
