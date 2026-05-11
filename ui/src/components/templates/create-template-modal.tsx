'use client';
import { zodResolver } from '@hookform/resolvers/zod';
import { useForm } from 'react-hook-form';
import { toast } from 'sonner';
import { z } from 'zod';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { TemplateBodyEditor } from '@/components/templates/template-body-editor';
import { useCreateTemplate } from '@/lib/api/query-templates';
import { ENGINE_TYPE_VALUES, type EngineType } from '@/lib/enums';

const DeclaredParamSchema = z.string().regex(/^[a-zA-Z_][\w]*\s*:\s*\S+$/, {
  message: 'Use `name:type` (e.g. `boost:float`).',
});

const CreateTemplateSchema = z.object({
  name: z.string().min(1).max(256),
  engine_type: z.enum(ENGINE_TYPE_VALUES),
  body: z.string().min(1, 'Body is required'),
  declared_params_raw: z.string().optional(),
});

type FormValues = z.infer<typeof CreateTemplateSchema>;

function parseDeclaredParams(raw: string | undefined): Record<string, string> {
  if (!raw) return {};
  const out: Record<string, string> = {};
  for (const line of raw.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const ok = DeclaredParamSchema.safeParse(trimmed);
    if (!ok.success) {
      throw new Error(`Invalid declared param: "${trimmed}". ${ok.error.errors[0]?.message ?? ''}`);
    }
    const [name, type] = trimmed.split(':').map((s) => s.trim());
    // `name` matches /^[a-zA-Z_][\w]*/ via DeclaredParamSchema above — safe object key.
    // eslint-disable-next-line security/detect-object-injection
    if (name && type) out[name] = type;
  }
  return out;
}

export interface CreateTemplateModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CreateTemplateModal({ open, onOpenChange }: CreateTemplateModalProps) {
  const create = useCreateTemplate();
  const form = useForm<FormValues>({
    // zod 3.24 + @hookform/resolvers 3.10's type signature has a known v3/v4
    // mismatch when zod@4 is anywhere in the lockfile (transitive). The
    // runtime is fine — only the type narrows. Cast to silence the inference.
    resolver: zodResolver(CreateTemplateSchema as unknown as never),
    defaultValues: { name: '', engine_type: 'elasticsearch', body: '', declared_params_raw: '' },
  });

  function onSubmit(values: FormValues) {
    let declared_params: Record<string, string>;
    try {
      declared_params = parseDeclaredParams(values.declared_params_raw);
    } catch (e) {
      form.setError('declared_params_raw', { message: (e as Error).message });
      return;
    }
    create.mutate(
      {
        name: values.name,
        engine_type: values.engine_type as EngineType,
        body: values.body,
        declared_params,
        parent_id: null,
      },
      {
        onSuccess: () => {
          toast.success('Template created');
          form.reset();
          onOpenChange(false);
        },
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Create query template</DialogTitle>
          <DialogDescription>
            A template renders to engine Query DSL via Jinja2. Declared parameters bind to study
            search-space variables.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="tpl-name">Name</Label>
            <Input id="tpl-name" {...form.register('name')} />
            {form.formState.errors.name && (
              <p className="text-xs text-destructive">{form.formState.errors.name.message}</p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="tpl-engine">Engine</Label>
            <Select
              value={form.watch('engine_type')}
              onValueChange={(v) => form.setValue('engine_type', v as EngineType)}
            >
              <SelectTrigger id="tpl-engine">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {ENGINE_TYPE_VALUES.map((v) => (
                  <SelectItem key={v} value={v}>
                    {v}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>Body (Jinja2 → engine DSL)</Label>
            <TemplateBodyEditor
              value={form.watch('body')}
              onChange={(v) => form.setValue('body', v, { shouldValidate: true })}
            />
            {form.formState.errors.body && (
              <p className="text-xs text-destructive">{form.formState.errors.body.message}</p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="tpl-params">
              Declared params (one per line, `name:type`) — optional
            </Label>
            <textarea
              id="tpl-params"
              {...form.register('declared_params_raw')}
              rows={4}
              className="flex w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              placeholder={'boost:float\nslop:int'}
            />
            {form.formState.errors.declared_params_raw && (
              <p className="text-xs text-destructive">
                {form.formState.errors.declared_params_raw.message}
              </p>
            )}
          </div>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? 'Creating…' : 'Create'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
