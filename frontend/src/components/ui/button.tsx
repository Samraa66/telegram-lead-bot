import React from "react";
import { cn } from "../../lib/utils";

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "default" | "outline" | "secondary";
  size?: "sm" | "md";
};

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className = "", variant = "default", size = "md", ...props }, ref) => {
    const base = "inline-flex items-center justify-center font-medium transition-colors disabled:opacity-50";
    const variantCls =
      variant === "outline"
        ? "border border-border bg-transparent"
        : variant === "secondary"
          ? "bg-secondary text-secondary-foreground"
          : "bg-primary text-primary-foreground";
    const sizeCls = size === "sm" ? "h-8 px-3 text-sm" : "h-10 px-4";
    return <button ref={ref} className={cn(base, variantCls, sizeCls, className)} {...props} />;
  }
);
Button.displayName = "Button";
