"use client";

import { useFormStatus } from "react-dom";

type SubmitButtonProps = {
  children: React.ReactNode;
  pendingText?: string;
  className?: string;
  title?: string;
  disabled?: boolean;
};

export function SubmitButton({
  children,
  pendingText = "处理中...",
  className = "button",
  title,
  disabled = false
}: SubmitButtonProps) {
  const { pending } = useFormStatus();

  return (
    <button
      aria-busy={pending}
      className={className}
      disabled={disabled || pending}
      title={title}
      type="submit"
    >
      {pending ? pendingText : children}
    </button>
  );
}
