import React from 'react';

export default function ChallengePanel({ question }) {
  if (!question) return null;
  return <details className="p-3 border-b border-ide-border text-sm">
    <summary className="cursor-pointer font-semibold">Challenge: {question.title}</summary>
    <div className="mt-2 whitespace-pre-wrap text-ide-textMuted max-h-64 overflow-auto">{question.question}</div>
  </details>;
}
