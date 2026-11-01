import type { QualityMetricSet } from './types';

export interface JudgedDoc {
  id: string;
  grade: number;
}

function dcgAt(rankedIds: string[], grades: Map<string, number>, k: number): number {
  let sum = 0;
  const limit = Math.min(k, rankedIds.length);
  for (let index = 0; index < limit; index += 1) {
    const grade = grades.get(rankedIds[index]) ?? 0;
    if (grade > 0) sum += (2 ** grade - 1) / Math.log2(index + 2);
  }
  return sum;
}

export function rankingMetrics(rankedIds: string[], relevant: JudgedDoc[]): QualityMetricSet {
  const grades = new Map(relevant.map((item) => [item.id, item.grade]));
  const relevantCount = Math.max(1, relevant.length);
  const hitAt = (k: number) => rankedIds.slice(0, k).filter((id) => (grades.get(id) ?? 0) > 0).length / relevantCount;

  const idealGrades = relevant
    .map((item) => item.grade)
    .sort((a, b) => b - a)
    .slice(0, 10);
  let ideal = 0;
  idealGrades.forEach((grade, index) => {
    ideal += (2 ** grade - 1) / Math.log2(index + 2);
  });

  const firstHit = rankedIds.slice(0, 10).findIndex((id) => (grades.get(id) ?? 0) > 0);

  return {
    'Recall@5': hitAt(5),
    'Recall@10': hitAt(10),
    'nDCG@10': ideal > 0 ? dcgAt(rankedIds, grades, 10) / ideal : 0,
    'MRR@10': firstHit >= 0 ? 1 / (firstHit + 1) : 0,
  };
}

export function averageMetrics(sets: QualityMetricSet[]): QualityMetricSet {
  if (sets.length === 0) {
    return { 'Recall@5': 0, 'Recall@10': 0, 'nDCG@10': 0, 'MRR@10': 0 };
  }
  const keys = Object.keys(sets[0]) as (keyof QualityMetricSet)[];
  const result = {} as QualityMetricSet;
  for (const key of keys) {
    result[key] = sets.reduce((sum, item) => sum + item[key], 0) / sets.length;
  }
  return result;
}
