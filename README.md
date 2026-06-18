# spider_utils
爬虫工具库，解析，文本标准化等，爬虫常用的方法和工具函数。

爬虫工具库，所以叫spider_utils，但是没名字被占用了【失落】。
星梦工具库，所以叫sd_utils，但是没名字被占用了【超失落】。
所以【杀手锏来了】：星梦爬虫工具库【灵光乍现】，sd_spider_utils，哈哈哈，这次没人用了【叉腰，得意】

```bash

pip install build twine
python -m build
twine upload dist/*

```

```bash
# 打标签之后自动发布
# 改 pyproject.toml: version = "1.0.3"
git add .
git commit -m "release 1.0.3"
git tag v1.0.3
git push origin main --tags
```