# Missing Tools Report

以下工具需要根据企业数据/API现状确认或实现：

## category_top_products_300
获取指定类目行业前300商品榜单

候选来源：
- internal_dw.category_top_products
- bi_api.market_insight_rank
- browser.sycm_market_rank_export
- browser.diantoushi_export
- manual_upload.top_products_excel

## category_keywords_top300
获取类目TOP300关键词及搜索人气、增长率、竞争度

候选来源：
- internal_dw.category_keyword_rank
- bi_api.category_keywords
- browser.sycm_keyword_export
- browser.taobao_suggest_collect
- manual_upload.keyword_excel

## competitor_reviews_qa
获取同类型排名前10竞品评价、问大家、中差评、追评

候选来源：
- internal_dw.competitor_reviews_qa
- browser.taobao_reviews_qa_collect
- manual_upload.review_qa_excel

## price_band_distribution
获取各价格带商品数、销量占比、GMV占比、竞争强度、毛利空间

候选来源：
- internal_dw.price_band_distribution
- compute.from_category_top_products
- manual_upload.price_band_excel

## competitor_landscape
获取竞品基础信息、价格、SKU、卖点、视觉、评价、流量结构

候选来源：
- internal_dw.competitor_landscape
- browser.taobao_competitor_collect
- compute.from_top_products_and_reviews
- manual_upload.competitor_excel

## cross_platform_trend_signals
获取小红书、抖音、公开网页中的趋势内容、热点元素、评论需求

候选来源：
- browser.xhs_high_like_notes
- browser.douyin_hot_products
- external_web.exa_trend_search
- manual_upload.cross_platform_excel
