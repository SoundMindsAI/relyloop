// SPDX-FileCopyrightText: 2026 soundminds.ai
//
// SPDX-License-Identifier: Apache-2.0

'use client';
import { useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { useOverrideJudgment, type JudgmentRow } from '@/lib/api/judgments';
import { RATING_VALUES } from '@/lib/enums';

export interface OverridePopoverProps {
  listId: string;
  judgment: JudgmentRow;
}

export function OverridePopover({ listId, judgment }: OverridePopoverProps) {
  const [open, setOpen] = useState(false);
  const [rating, setRating] = useState<number>(judgment.rating);
  const [notes, setNotes] = useState<string>(judgment.notes ?? '');
  const override = useOverrideJudgment(listId);

  function submit() {
    override.mutate(
      { judgmentId: judgment.id, rating, notes: notes || null },
      {
        onSuccess: () => {
          toast.success('Override saved');
          setOpen(false);
        },
      },
    );
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          data-testid={`override-trigger-${judgment.id}`}
          onClick={() => {
            setRating(judgment.rating);
            setNotes(judgment.notes ?? '');
          }}
        >
          Override
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80">
        <form
          className="space-y-3"
          data-testid={`override-form-${judgment.id}`}
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor={`rating-${judgment.id}`}>Rating</Label>
            <Select value={String(rating)} onValueChange={(v) => setRating(Number(v))}>
              <SelectTrigger id={`rating-${judgment.id}`} data-testid="override-rating">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {RATING_VALUES.map((v) => (
                  <SelectItem key={v} value={String(v)}>
                    {v}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor={`notes-${judgment.id}`}>Notes</Label>
            <Textarea
              id={`notes-${judgment.id}`}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={3}
              data-testid="override-notes"
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" size="sm" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              type="submit"
              size="sm"
              disabled={override.isPending}
              data-testid="override-save"
            >
              {override.isPending ? 'Saving…' : 'Save'}
            </Button>
          </div>
        </form>
      </PopoverContent>
    </Popover>
  );
}
