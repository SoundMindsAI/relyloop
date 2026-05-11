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
import { useCancelStudy, type StudyDetail } from '@/lib/api/studies';

export interface StudyActionBarProps {
  study: StudyDetail;
}

export function StudyActionBar({ study }: StudyActionBarProps) {
  const [open, setOpen] = useState(false);
  const cancel = useCancelStudy(study.id);
  const canCancel = study.status === 'running' || study.status === 'queued';
  return (
    <div className="flex items-center gap-3">
      <Button
        variant="destructive"
        disabled={!canCancel || cancel.isPending}
        onClick={() => setOpen(true)}
        data-testid="cancel-study"
      >
        {cancel.isPending ? 'Cancelling…' : 'Cancel study'}
      </Button>
      <AlertDialog open={open} onOpenChange={setOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Cancel &ldquo;{study.name}&rdquo;?</AlertDialogTitle>
            <AlertDialogDescription>
              In-flight trials may still finish and post results, but no new trials will start.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep running</AlertDialogCancel>
            <AlertDialogAction
              data-testid="confirm-cancel"
              onClick={() => {
                cancel.mutate(undefined, {
                  onSuccess: () => toast.success('Study cancelled'),
                });
              }}
            >
              Cancel study
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
