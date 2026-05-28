<!-- @Date: 2026-05-27 @Author: xisy @Discription: 教案生成并发真实测试报告 -->

# 教案生成并发真实测试报告

本报告由 `backend/scripts/run_lesson_plan_concurrency_realtest.py` 自动生成，用于验证教案生成任务在第 1 课暖缓存后对后续课次进行并发生成。

## 测试对象

- 课程大纲 ID：`9`
- 生成批次 ID：`13`
- 教案任务 ID：`37`
- 任务状态：`success`
- 生成教案数：`7`

## 并发观测

- total_sessions：`7`
- processed_sessions：`7`
- parallel_limit：`6`
- cache_warmup_completed：`True`
- llm_usage：`{"call_count": 7, "total_tokens": 110461, "cached_tokens": 55040, "prompt_tokens": 88075, "completion_tokens": 22386}`

## LLM 调用事件

- llm_start 第 1 讲，thread=`MainThread`，at=`244602.333147875`，elapsed=`None`
- llm_done 第 1 讲，thread=`MainThread`，at=`244758.401556458`，elapsed=`156.068`
- llm_start 第 2 讲，thread=`lesson-plan_0`，at=`244758.406591375`，elapsed=`None`
- llm_start 第 3 讲，thread=`lesson-plan_1`，at=`244758.406721166`，elapsed=`None`
- llm_start 第 4 讲，thread=`lesson-plan_2`，at=`244758.413734875`，elapsed=`None`
- llm_start 第 5 讲，thread=`lesson-plan_3`，at=`244758.4151785`，elapsed=`None`
- llm_start 第 6 讲，thread=`lesson-plan_4`，at=`244758.416548375`，elapsed=`None`
- llm_start 第 7 讲，thread=`lesson-plan_5`，at=`244758.418030916`，elapsed=`None`
- llm_done 第 5 讲，thread=`lesson-plan_3`，at=`244898.530321583`，elapsed=`140.115`
- llm_done 第 7 讲，thread=`lesson-plan_5`，at=`244900.570741708`，elapsed=`142.153`
- llm_done 第 2 讲，thread=`lesson-plan_0`，at=`244907.897665041`，elapsed=`149.491`
- llm_done 第 4 讲，thread=`lesson-plan_2`，at=`244915.557092166`，elapsed=`157.143`
- llm_done 第 3 讲，thread=`lesson-plan_1`，at=`244915.717122416`，elapsed=`157.31`
- llm_done 第 6 讲，thread=`lesson-plan_4`，at=`244949.841711375`，elapsed=`191.425`

## 生成教案

- 第 1 讲：并发测试第1讲：人物介绍、位置描述与正在做什么
  摘要：本课面向五年级英语基础薄弱学生，以Story Time情境学习为载体，围绕人物介绍、人物确认、方位描述、现在进行时问答和This is/These are单复数区分展开，通过卡片匹配、实景描述、图片问答和短阅读定位提升学生基础表达与阅读信息提取能力。
- 第 2 讲：并发测试第2讲：月份生日、问路电话与朋友交际综合运用
  摘要：本课面向五年级英语基础薄弱学生，以Story Time情境为载体，围绕月份生日、问路乘车、电话交际和朋友数量问答开展听说读写结合训练，帮助学生在句型支架下完成基础交际表达和信息定位。
- 第 3 讲：并发测试第3讲：人物介绍、位置描述与正在做什么
  摘要：本课面向五年级英语基础薄弱学生，通过卡片、实物位置、动作图片和Story Time短阅读，训练基础问候、人物身份确认、方位描述、现在进行时问答以及This is/These are单复数表达。
- 第 4 讲：并发测试第4讲：月份生日、问路电话与朋友交际综合运用
  摘要：本课面向五年级英语基础薄弱学生，以Story Time情境学习为依托，围绕月份生日、问路乘车、电话交际和朋友数量问答进行90分钟综合训练，重点提升词汇认读、句型替换、情景对话和阅读信息定位能力。
- 第 5 讲：并发测试第5讲：人物介绍、位置描述与正在做什么
  摘要：本课面向五年级英语基础薄弱学生，以Story Time情境为载体，围绕问候介绍、人物确认、方位描述、正在进行时问答和单复数介绍展开，通过卡片匹配、实物演示、图片问答、短阅读定位和口头复述提升学生基础表达信心。
- 第 6 讲：并发测试第6讲：月份生日、问路电话与朋友交际综合运用
  摘要：本课面向五年级英语基础薄弱学生，以Story Time情境学习为依托，围绕月份生日、节日月份、问路乘车、电话交际和朋友数量问答进行90分钟综合训练，通过词卡排序、调查采访、地图问路、电话角色扮演和阅读定位，帮助学生建立可复用的基础交际句型。
- 第 7 讲：并发测试第7讲：人物介绍、位置描述与正在做什么
  摘要：本课面向五年级英语基础薄弱学生，以Story Time情境为依托，通过问候接龙、人物卡片、教室实景、动作图片和短阅读定位，训练人物介绍、人物确认、方位描述、现在进行时问答及This is/These are单复数表达。