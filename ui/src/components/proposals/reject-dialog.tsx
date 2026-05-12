'use client';
import { useState } from 'react';
import { toast } from 'sonner';

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { useRejectProposal, type ProposalDetail } from '@/lib/api/proposals';

export interface RejectDialogProps {
  proposal: ProposalDetail;
}

export function RejectDialog({ proposal }: RejectDialogProps) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState('');
  const reject = useRejectProposal();

  if (proposal.status !== 'pending') return null;

  return (
    <>
      <Button
        type="button"
        variant="destructive"
        onClick={() => setOpen(true)}
        data-testid="open-reject-dialog"
      >
        Reject
      </Button>
      <AlertDialog open={open} onOpenChange={setOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Reject this proposal?</AlertDialogTitle>
            <AlertDialogDescription>
              Rejected proposals cannot be re-pended. Provide an optional reason for the audit
              trail.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="my-3">
            <Textarea
              value={reason}
              maxLength={500}
              placeholder="Optional reason…"
              onChange={(e) => setReason(e.target.value)}
              disabled={reject.isPending}
              data-testid="reject-reason-input"
            />
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={reject.isPending}>Keep pending</AlertDialogCancel>
            <AlertDialogAction
              disabled={reject.isPending}
              data-testid="confirm-reject"
              onClick={(event) => {
                // Keep the dialog open during the in-flight POST so the
                // operator sees the new state if a 409 INVALID_STATE_TRANSITION
                // refetches the detail (per GPT-5.5 cycle-1 B4).
                event.preventDefault();
                reject.mutate(
                  { proposalId: proposal.id, reason: reason || null },
                  {
                    onSuccess: () => {
                      toast.success('Proposal rejected');
                      setOpen(false);
                    },
                    // No onError — global MutationCache handler toasts on
                    // 409 INVALID_STATE_TRANSITION (and any other failure).
                  },
                );
              }}
            >
              {reject.isPending ? 'Rejecting…' : 'Reject proposal'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
