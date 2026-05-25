'use client';
import { useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
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
import { InfoTooltip } from '@/components/common/info-tooltip';
import { Label } from '@/components/ui/label';
import { useCancelStudy, type StudyDetail, type StudySummary } from '@/lib/api/studies';

export interface StudyActionBarProps {
  study: StudyDetail;
  /**
   * Direct chain children for the cancel-modal cascade decision
   * (feat_auto_followup_studies Story 3.3 + cycle-2 finding C2-4).
   *
   * Prop is named `chainChildren` (NOT `children`) to avoid collision
   * with React's built-in `children` prop semantics. Defaults to `[]`
   * so the existing callers that don't pass it keep their pre-Story-3.3
   * behavior (radio hidden = simple cancel).
   */
  chainChildren?: StudySummary[];
}

export function StudyActionBar({ study, chainChildren = [] }: StudyActionBarProps) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  // Per spec D-6: default the cascade radio to "true" when shown.
  const [cascade, setCascade] = useState(true);
  // feat_study_clone_from_previous FR-11: when cloning a `running` source,
  // surface an AlertDialog asking the operator to confirm. Terminal-state
  // sources (completed/failed/cancelled/queued) navigate directly without
  // the dialog.
  const [cloneConfirmOpen, setCloneConfirmOpen] = useState(false);
  const cancel = useCancelStudy(study.id);
  const canCancel = study.status === 'running' || study.status === 'queued';

  const navigateToClone = () => {
    router.push(`/studies?clone_from=${study.id}`);
  };
  const handleClone = () => {
    if (study.status === 'running') {
      setCloneConfirmOpen(true);
    } else {
      navigateToClone();
    }
  };

  // Per FR-8 + cycle-1 C1-8 + cycle-2 C2-4: show the cascade radio when
  // EITHER (a) the parent has an in-flight direct child, OR (b) the
  // parent is `running` with auto_followup_depth > 0 (anticipated child).
  const showCascadeRadio = useMemo(() => {
    const hasInFlightChild = chainChildren.some(
      (c) => c.status === 'queued' || c.status === 'running',
    );
    const depth =
      typeof study.config?.auto_followup_depth === 'number' ? study.config.auto_followup_depth : 0;
    const anticipatedChild = study.status === 'running' && depth > 0;
    return hasInFlightChild || anticipatedChild;
  }, [chainChildren, study.status, study.config?.auto_followup_depth]);

  return (
    <div className="flex items-center gap-3">
      <Button variant="outline" onClick={handleClone} data-testid="clone-study">
        Clone study
      </Button>
      <InfoTooltip glossaryKey="study.clone_button" />
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
          {showCascadeRadio && (
            <fieldset data-testid="cancel-cascade-radio-group" className="space-y-2 px-1 pb-2">
              <legend className="sr-only">Cancel scope</legend>
              <div className="flex items-start gap-3">
                <input
                  id="cascade-true"
                  type="radio"
                  name="cancel-cascade"
                  className="mt-1 h-4 w-4 cursor-pointer"
                  checked={cascade}
                  onChange={() => setCascade(true)}
                  data-testid="cascade-true"
                />
                <Label htmlFor="cascade-true" className="font-normal leading-snug">
                  Cancel parent + in-flight children
                  <span className="block text-xs text-muted-foreground">
                    Stops the whole auto-followup chain rooted at this study.
                  </span>
                </Label>
              </div>
              <div className="flex items-start gap-3">
                <input
                  id="cascade-false"
                  type="radio"
                  name="cancel-cascade"
                  className="mt-1 h-4 w-4 cursor-pointer"
                  checked={!cascade}
                  onChange={() => setCascade(false)}
                  data-testid="cascade-false"
                />
                <Label htmlFor="cascade-false" className="font-normal leading-snug">
                  Cancel parent only
                  <span className="block text-xs text-muted-foreground">
                    In-flight children keep running and finish independently.
                  </span>
                </Label>
              </div>
            </fieldset>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel>Keep running</AlertDialogCancel>
            <AlertDialogAction
              data-testid="confirm-cancel"
              onClick={() => {
                cancel.mutate(
                  { cascade },
                  {
                    onSuccess: () =>
                      toast.success(
                        showCascadeRadio && cascade ? 'Chain cancelled' : 'Study cancelled',
                      ),
                  },
                );
              }}
            >
              Cancel study
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      <AlertDialog open={cloneConfirmOpen} onOpenChange={setCloneConfirmOpen}>
        <AlertDialogContent data-testid="clone-running-confirm">
          <AlertDialogHeader>
            <AlertDialogTitle>Clone an in-progress study?</AlertDialogTitle>
            <AlertDialogDescription>
              &ldquo;{study.name}&rdquo; is still running. The clone will use the current
              configuration but its trials are still being tuned.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              data-testid="clone-confirm-proceed"
              onClick={() => {
                setCloneConfirmOpen(false);
                navigateToClone();
              }}
            >
              Clone anyway
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
