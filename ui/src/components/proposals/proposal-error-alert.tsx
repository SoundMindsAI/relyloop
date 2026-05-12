'use client';

export interface ProposalErrorAlertProps {
  error: string;
}

export function ProposalErrorAlert({ error }: ProposalErrorAlertProps) {
  return (
    <div
      role="alert"
      data-testid="proposal-error-alert"
      className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-900"
    >
      <p className="font-semibold">Open-PR worker reported an error</p>
      <p className="mt-1 whitespace-pre-wrap">{error}</p>
    </div>
  );
}
