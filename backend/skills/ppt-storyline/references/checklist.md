# 检查项

和 `ppt_story_check.py` 的规则编号对应。Q1 实现时按这张表写判断，改一边就要改另一边。

| 编号 | 级别 | 没通过 | 怎么改 |
|---|---|---|---|
| S_NO_BACKGROUND | error | 第一个内容章节的第一张内容页不是背景、引子或概念 | 把该页改成背景，或在它前面加一页背景 |
| S_NO_QUESTION | error | 研究类、答辩、开题、文献汇报前 40% 的页里没有研究问题 | 在背景之后加一页，标题写成要回答的问题 |
| S_NO_METHOD | warn | 研究类、答辩、开题、调研没有方法页 | 加一页方法，写材料、步骤或对象 |
| S_NO_SUMMARY | error | 结尾页前面那一页不是总结 | 在结尾前加一页总结 |
| S_SUMMARY_NOT_ANSWER | warn | 总结页的文字里没有中心问题的实词 | 总结的每句话回扣中心问题 |
| S_SECTION_HEAVY | error | 章节页超过 25% 或超过页数表的上限 | 合并章节，每章至少两张内容页 |
| S_THIN_SECTION | error | 某一章内容页少于 2 张 | 并进相邻章节，或补一页 |
| S_TITLE_NOT_ASSERTION | warn | 内容页标题少于 8 字，或没有判断 | 改成一句有主语的判断 |
| S_NO_LEAD | warn | 内容页（每章第一张除外）没有承接句，讲稿开头也没有承接词 | 补 lead，或把承接写进讲稿第一句 |
| S_NOTES_SHORT | error | 内容页讲稿少于 80 字 | 按「承接、证据、引出下一页」补讲稿 |
| S_TOC_MISMATCH | error | 目录项和章节页数量或名字对不上 | 目录改成章节名 |
| S_DUP_MESSAGE | warn | 两页标题的字二元组相似度超过 0.6 | 合并，或改成不同的判断 |
| S_FORM_REPEAT | warn | 同一种形态连续 3 页以上 | 换一页的形态 |
| S_EVIDENCE_MISSING | warn | 骨架里写了材料不足 | 在卡片上标明，不编造 |
