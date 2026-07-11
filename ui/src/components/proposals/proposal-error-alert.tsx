// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';

import { Alert } from '@/components/ui/alert';

export interface ProposalErrorAlertProps {
  error: string;
}

export function ProposalErrorAlert({ error }: ProposalErrorAlertProps) {
  return (
    <Alert variant="destructive" data-testid="proposal-error-alert">
      <p className="font-semibold">Open-PR worker reported an error</p>
      <p className="mt-1 whitespace-pre-wrap">{error}</p>
    </Alert>
  );
}
