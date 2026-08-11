/**
 * 复用 RAGFlow 项目中已定义的 CS Interview 类型（单一来源，只读导入）。
 * 这些类型镜像后端协议，保持与真实服务一致，后续可无缝切换真实后端。
 */
import type {
  InterviewResume,
  JDRequirement,
} from '../../../web/src/interfaces/database/cs-interview';

export type { InterviewResume, JDRequirement };

export * from '../../../web/src/interfaces/database/cs-interview';

/** —— 产品层补充类型 —— */

/** 证据轨道节点状态。 */
export type EvidenceState =
  | 'pending'
  | 'verifying'
  | 'proven'
  | 'insufficient'
  | 'contradicted';

export interface EvidenceNode {
  key: 'claim' | 'requirement' | 'question' | 'answer' | 'conclusion';
  label: string;
  state: EvidenceState;
  hint?: string;
}

/** 面试流式处理阶段（对应真实 SSE 事件语义）。 */
export type StreamStage =
  | 'received'
  | 'evaluating'
  | 'feedback'
  | 'deciding'
  | 'next'
  | 'followup'
  | 'completed'
  | 'error';

/** 简历高风险声明（在简历详情页生成，供面试计划与报告引用）。 */
export interface HighRiskClaim {
  id: string;
  claim: string;
  source: string;
  reason: string;
  topics: string[];
}

/** 简历解析结果 + 高风险声明的展示载体。 */
export interface ResumeDetailView {
  resume: InterviewResume;
  highRiskClaims: HighRiskClaim[];
}

/** JD 覆盖情况展示载体。 */
export interface JobCoverageView {
  mustHave: JDRequirement[];
  niceToHave: JDRequirement[];
  coveredCount: number;
  uncoveredCount: number;
}

/** 面试报告——三个业务问题的聚合视图。 */
export interface ReportSummary {
  matchPercent: number;
  verifiedCount: number;
  highRiskCount: number;
  disputedCount: number;
  nextFocus: string;
}
