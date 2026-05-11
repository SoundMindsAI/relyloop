'use client';
import { useTheme } from 'next-themes';
import { Toaster as SonnerToaster, type ToasterProps } from 'sonner';

/** Theme-aware Toaster wrapper. */
export function Toaster({ ...props }: ToasterProps) {
  const { theme = 'system' } = useTheme();
  return (
    <SonnerToaster
      theme={theme as ToasterProps['theme']}
      className="toaster group"
      richColors
      closeButton
      {...props}
    />
  );
}
