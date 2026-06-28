from __future__ import annotations

import re
from pathlib import Path
from .schemas import (
    BusinessQuestion,
    DataRequirement,
    OutputSpec,
    RuleSpec,
    StrategyIR,
    WorkflowStep,
)


class DocumentParser:
    """Markdown-first parser for business strategy documents.

    MVP is deterministic and tuned for the market insight strategy doc.
    Production version should add Docling / MarkItDown / LLM structured extraction.
    """

    def parse(self, path: str | Path) -> StrategyIR:
        path = Path(path)
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            raise ValueError(f"Empty document: {path}")

        sections = self._split_sections(text)
        name = self._extract_title(text) or path.stem

        return StrategyIR(
            strategy_id="market_insight",
            name=name,
            source_doc=path.name,
            business_scenes=self._extract_business_scenes(text),
            business_questions=self._extract_business_questions(text),
            outputs=self._extract_outputs(text),
            workflow_steps=self._extract_workflow_steps(text),
            data_requirements=self._default_market_insight_data_requirements(),
            rules=self._extract_rules(text),
            raw_sections=sections,
        )

    def _extract_title(self, text: str) -> str | None:
        match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        return match.group(1).strip() if match else None

    def _split_sections(self, text: str) -> dict[str, str]:
        headers = list(re.finditer(r"^#\s+(.+)$", text, re.MULTILINE))
        sections: dict[str, str] = {}
        for idx, match in enumerate(headers):
            start = match.end()
            end = headers[idx + 1].start() if idx + 1 < len(headers) else len(text)
            sections[match.group(1).strip()] = text[start:end].strip()
        return sections

    def _extract_business_scenes(self, text: str) -> list[str]:
        known = [
            "淘宝 / 天猫新品开发",
            "爆款机会挖掘",
            "类目市场分析",
            "主图与视觉策划",
            "竞品分析",
            "价格带布局",
            "产品升级与迭代",
            "跨平台趋势机会挖掘",
            "季节性产品提前布局",
            "店铺产品结构规划",
        ]
        return [x for x in known if x.replace(" ", "") in text.replace(" ", "")]

    def _extract_business_questions(self, text: str) -> list[BusinessQuestion]:
        questions = [
            ("what_sells_well", "这个类目现在什么东西卖得好？", ["category_market_analysis_table", "top_300_product_analysis_table"]),
            ("what_grows_fast", "这个类目什么东西涨得快？", ["trend_product_list", "keyword_root_top20_table"]),
            ("what_users_search", "用户到底在搜什么？", ["keyword_demand_breakdown_table"]),
            ("what_users_care_or_complain", "用户真正关心和抱怨什么？", ["review_qa_painpoint_table"]),
            ("where_competition_is_weak", "哪些地方竞争没有那么强？", ["competitor_landscape_table"]),
            ("what_product_to_build", "我们应该做什么产品？", ["product_development_listing_plan"]),
            ("how_to_compete", "我们怎么和竞品打？", ["competitor_landscape_table"]),
            ("can_land_to_listing_plan", "最后能不能落到链接规划？", ["product_development_listing_plan"]),
        ]
        return [BusinessQuestion(id=qid, question=q, required_outputs=outs) for qid, q, outs in questions if q in text]

    def _extract_outputs(self, text: str) -> list[OutputSpec]:
        outputs = [
            ("category_market_analysis_table", "类目大盘分析表", "判断行业主流与趋势"),
            ("top_300_product_analysis_table", "行业前300商品分析表", "找爆款共性"),
            ("keyword_demand_breakdown_table", "关键词需求拆解表", "拆用户需求"),
            ("keyword_root_top20_table", "关键词词根TOP20表", "找趋势需求"),
            ("review_qa_painpoint_table", "评价/问大家痛点表", "找产品升级点"),
            ("price_band_opportunity_table", "价格带机会表", "判断价格空间"),
            ("competitor_landscape_table", "竞品竞争格局表", "找对标对象"),
            ("competitor_visual_service_comparison_table", "竞品主图/详情页/客服对比表", "找转化差异"),
            ("cross_platform_trend_table", "跨平台趋势素材表", "找外部机会"),
            ("product_development_listing_plan", "产品开发与链接规划表", "落到执行"),
        ]
        return [OutputSpec(id=oid, name=name, description=desc) for oid, name, desc in outputs if name in text]

    def _extract_workflow_steps(self, text: str) -> list[WorkflowStep]:
        steps = [
            WorkflowStep(step_id="define_scope", title="确定分析边界", step_type="form_collect", outputs=["market_insight_project_definition"]),
            WorkflowStep(step_id="collect_top_products", title="行业大盘与热销商品分析", step_type="data_collect", depends_on=["define_scope"], data_requirement_ids=["category_top_products_300"], outputs=["top_300_product_analysis_table"]),
            WorkflowStep(step_id="analyze_hot_product_genes", title="爆款基因提炼", step_type="compute_and_llm_extract", depends_on=["collect_top_products"], outputs=["hot_product_gene_table"]),
            WorkflowStep(step_id="collect_keywords", title="关键词需求分析", step_type="data_collect", depends_on=["define_scope"], data_requirement_ids=["category_keywords_top300"], outputs=["keyword_demand_breakdown_table", "keyword_root_top20_table"]),
            WorkflowStep(step_id="collect_reviews_qa", title="评价与问大家痛点分析", step_type="data_collect", depends_on=["collect_top_products"], data_requirement_ids=["competitor_reviews_qa"], outputs=["review_qa_painpoint_table"]),
            WorkflowStep(step_id="analyze_price_band", title="价格带与利润空间分析", step_type="compute", depends_on=["collect_top_products"], data_requirement_ids=["price_band_distribution"], outputs=["price_band_opportunity_table"]),
            WorkflowStep(step_id="analyze_competitors", title="竞品与竞店格局分析", step_type="multi_source_analysis", depends_on=["collect_top_products", "collect_reviews_qa"], data_requirement_ids=["competitor_landscape"], outputs=["competitor_landscape_table"]),
            WorkflowStep(step_id="collect_cross_platform_trends", title="跨平台趋势机会分析", step_type="external_research", depends_on=["define_scope", "collect_keywords"], data_requirement_ids=["cross_platform_trend_signals"], outputs=["cross_platform_trend_table"]),
            WorkflowStep(step_id="score_opportunities", title="机会判断与产品创新设计", step_type="scoring", depends_on=["analyze_hot_product_genes", "collect_keywords", "collect_reviews_qa", "analyze_price_band", "analyze_competitors", "collect_cross_platform_trends"], outputs=["product_opportunity_score_table"]),
            WorkflowStep(step_id="generate_listing_plan", title="产品开发与链接规划落地", step_type="business_plan_generation", depends_on=["score_opportunities"], outputs=["product_development_listing_plan"]),
        ]
        return [s for s in steps if s.title in text or s.step_id in {"define_scope", "score_opportunities", "generate_listing_plan"}]

    def _default_market_insight_data_requirements(self) -> list[DataRequirement]:
        return [
            DataRequirement(
                id="category_top_products_300",
                description="获取指定类目行业前300商品榜单",
                required_fields=["rank", "shop_name", "product_url", "product_image", "sales_or_pay_buyer_count", "gmv_or_transaction_index", "price", "price_band", "product_type", "material", "function", "style", "scene", "main_selling_point", "growth_7d", "growth_30d"],
                preferred_sources=["internal_dw.category_top_products", "bi_api.market_insight_rank", "browser.sycm_market_rank_export", "browser.diantoushi_export"],
                fallback_sources=["manual_upload.top_products_excel"],
            ),
            DataRequirement(
                id="category_keywords_top300",
                description="获取类目TOP300关键词及搜索人气、增长率、竞争度",
                required_fields=["keyword", "search_popularity", "growth_rate", "competition_index", "click_rate", "conversion_rate", "root_terms", "demand_type"],
                preferred_sources=["internal_dw.category_keyword_rank", "bi_api.category_keywords", "browser.sycm_keyword_export", "browser.taobao_suggest_collect"],
                fallback_sources=["manual_upload.keyword_excel"],
            ),
            DataRequirement(
                id="competitor_reviews_qa",
                description="获取同类型排名前10竞品评价、问大家、中差评、追评",
                required_fields=["competitor_product_url", "review_text", "sentiment", "rating", "qa_question", "qa_answer", "painpoint_type", "sku_name", "created_at"],
                preferred_sources=["internal_dw.competitor_reviews_qa", "browser.taobao_reviews_qa_collect"],
                fallback_sources=["manual_upload.review_qa_excel"],
            ),
            DataRequirement(
                id="price_band_distribution",
                description="获取各价格带商品数、销量占比、GMV占比、竞争强度、毛利空间",
                required_fields=["price_band", "product_count", "sales_ratio", "gmv_ratio", "avg_order_value", "competitor_count", "gross_margin_estimate"],
                preferred_sources=["internal_dw.price_band_distribution", "compute.from_category_top_products"],
                fallback_sources=["manual_upload.price_band_excel"],
            ),
            DataRequirement(
                id="competitor_landscape",
                description="获取竞品基础信息、价格、SKU、卖点、视觉、评价、流量结构",
                required_fields=["competitor_type", "shop_name", "product_url", "price", "sku_count", "main_selling_point", "visual_structure", "review_painpoints", "traffic_structure", "competitor_strength"],
                preferred_sources=["internal_dw.competitor_landscape", "browser.taobao_competitor_collect", "compute.from_top_products_and_reviews"],
                fallback_sources=["manual_upload.competitor_excel"],
            ),
            DataRequirement(
                id="cross_platform_trend_signals",
                description="获取小红书、抖音、公开网页中的趋势内容、热点元素、评论需求",
                required_fields=["platform", "content_url", "likes_or_sales", "topic", "product_elements", "audience", "scene", "comment_needs", "taobao_supply_status", "migration_method", "opportunity_level"],
                preferred_sources=["browser.xhs_high_like_notes", "browser.douyin_hot_products", "external_web.exa_trend_search"],
                fallback_sources=["manual_upload.cross_platform_excel"],
            ),
        ]

    def _extract_rules(self, text: str) -> list[RuleSpec]:
        return [
            RuleSpec(rule_id="strong_hot_gene", description="强爆款基因：TOP50占比、TOP100占比、支付买家数占比、GMV占比任意2项满足", condition="count(top50_ratio>=0.30, top100_ratio>=0.20, buyer_ratio>=0.30, gmv_ratio>=0.30) >= 2", output_label="强爆款基因"),
            RuleSpec(rule_id="trend_hot_gene", description="趋势爆款基因：高增速商品占比、关键词搜索增长、买家增长、跨平台内容高热任意2项满足", condition="count(high_growth_product_ratio>=0.30, keyword_growth>=0.20, buyer_growth_30d>=0.50, cross_platform_hot=true) >= 2", output_label="趋势爆款基因"),
            RuleSpec(rule_id="differentiated_opportunity_gene", description="差异机会基因：评价痛点、问大家顾虑、TOP50承接少、价格带供给不足任意2项满足", condition="count(review_painpoint_ratio>=0.10, qa_concern_ratio>=0.10, top50_supply_count<5, price_band_supply_ratio<0.15 and buyer_ratio>=0.25) >= 2", output_label="差异机会基因"),
            RuleSpec(rule_id="opportunity_score", description="机会评分=需求明确度20+增长趋势20+竞争强度15+利润空间15+供应链可行性15+差异化强度15", condition="total_score >= 85 => 优先立项开发; 70-84 => 小批量测试; 60-69 => 继续观察; <60 => 暂不开发", output_label="机会评分"),
        ]
