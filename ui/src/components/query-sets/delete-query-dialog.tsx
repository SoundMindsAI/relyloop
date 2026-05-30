// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';
import { useRouter } from 'next/navigation';
import { useState, type ReactNode } from 'react';

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import { useDeleteQuery, type QueryRow } from '@/lib/api/query-sets';

export interface DeleteQueryDialogProps {
  querySetId: string;
  query: QueryRow;
  trigger: ReactNode;
}

export function DeleteQueryDialog({ querySetId, query, trigger }: DeleteQueryDialogProps) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const del = useDeleteQuery(querySetId, {
    onOpenJudgmentList: (judgmentListId) => {
      router.push(`/judgments/${judgmentListId}`);
    },
    onSuccess: () => setOpen(false),
  });

  return (
    <AlertDialog open={open} onOpenChange={setOpen}>
      <AlertDialogTrigger asChild>{trigger}</AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete query?</AlertDialogTitle>
          <AlertDialogDescription>
            This permanently removes the query. Judgments must be removed first.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={del.isPending}>Cancel</AlertDialogCancel>
          <AlertDialogAction
            onClick={(event) => {
              // Keep dialog open during the in-flight DELETE so the operator can
              // see the pending state. The hook's onSuccess closes it; on 409
              // the dialog stays open so the operator can read the toast.
              event.preventDefault();
              del.mutate(query.id);
            }}
            disabled={del.isPending}
            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            data-testid="confirm-delete-query"
          >
            {del.isPending ? 'Deleting…' : 'Delete query'}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
