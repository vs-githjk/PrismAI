import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { Slot } from "radix-ui"

import { cn } from "@/lib/utils"

// PrismAI "codify current" button — variants use the app's REAL cyan/white/rose
// glass classes (not shadcn theme vars), so adopting <Button> is a visual no-op.
// Split of concerns: VARIANT = color/surface only; SIZE = padding/height/text/
// weight/radius. Radius lives on the size because the app has two solid-cyan
// shapes — a full pill CTA and a small rounded-lg inline action — that differ by
// a genuinely-visible corner, not by color.
// Approved variant API: primary | accent | ghost | danger | subtle | link.
// Legacy shadcn names (default/outline/secondary/destructive) are kept as aliases
// so existing call sites — e.g. ui/dialog — don't break during migration.
const buttonVariants = cva(
  "group/button inline-flex shrink-0 items-center justify-center rounded-lg border border-transparent bg-clip-padding text-sm font-medium whitespace-nowrap transition-all outline-none select-none focus-visible:ring-2 focus-visible:ring-cyan-400/50 active:not-aria-[haspopup]:translate-y-px disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        // Approved API — color/surface only (radius comes from size)
        primary:
          "border-transparent bg-cyan-400 text-[#07040f] hover:bg-cyan-300",
        accent:
          "border-cyan-400/30 bg-cyan-400/10 text-cyan-200 hover:bg-cyan-400/[0.16] hover:text-cyan-100",
        ghost:
          "border-white/10 bg-white/5 text-white/75 hover:bg-white/10 hover:text-white/90 aria-expanded:bg-white/10",
        // Borderless, transparent icon button (close ✕, subtle inline controls) —
        // the second real icon flavor alongside the bordered-glass `ghost`+icon size.
        subtle:
          "border-transparent bg-transparent text-white/40 hover:bg-white/[0.07] hover:text-white/70",
        danger:
          "border-rose-400/40 bg-rose-400/15 text-rose-200 hover:bg-rose-400/25",
        link: "border-transparent text-cyan-300 underline-offset-4 hover:underline",
        // Legacy aliases (map to the closest approved look)
        default:
          "border-transparent bg-cyan-400 text-[#07040f] hover:bg-cyan-300",
        outline:
          "border-white/10 bg-white/5 text-white/75 hover:bg-white/10 hover:text-white/90 aria-expanded:bg-white/10",
        secondary:
          "border-white/10 bg-white/5 text-white/75 hover:bg-white/10 hover:text-white/90 aria-expanded:bg-white/10",
        destructive:
          "border-rose-400/40 bg-rose-400/15 text-rose-200 hover:bg-rose-400/25",
      },
      size: {
        // App-real shapes:
        // `cta`    — full-width panel CTA: rounded-full pill, ~40px, semibold. Pair with `w-full`.
        // `inline` — compact solid/tint action (px-3 py-1 text-[11px] semibold), base rounded-lg.
        cta: "h-10 gap-1.5 rounded-full px-4 text-sm font-semibold",
        inline: "gap-1.5 px-3 py-1 text-[11px] font-semibold",
        default:
          "h-8 gap-1.5 px-2.5 has-data-[icon=inline-end]:pr-2 has-data-[icon=inline-start]:pl-2",
        xs: "h-6 gap-1 rounded-[min(var(--radius-md),10px)] px-2 text-xs in-data-[slot=button-group]:rounded-lg has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 [&_svg:not([class*='size-'])]:size-3",
        sm: "h-7 gap-1 rounded-[min(var(--radius-md),12px)] px-2.5 text-[0.8rem] in-data-[slot=button-group]:rounded-lg has-data-[icon=inline-end]:pr-1.5 has-data-[icon=inline-start]:pl-1.5 [&_svg:not([class*='size-'])]:size-3.5",
        lg: "h-9 gap-1.5 px-2.5 has-data-[icon=inline-end]:pr-2 has-data-[icon=inline-start]:pl-2",
        icon: "size-8",
        "icon-xs":
          "size-6 rounded-[min(var(--radius-md),10px)] in-data-[slot=button-group]:rounded-lg [&_svg:not([class*='size-'])]:size-3",
        "icon-sm":
          "size-7 rounded-[min(var(--radius-md),12px)] in-data-[slot=button-group]:rounded-lg",
        "icon-lg": "size-9",
      },
    },
    defaultVariants: {
      variant: "primary",
      size: "default",
    },
  }
)

function Button({
  className,
  variant = "primary",
  size = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean
  }) {
  const Comp = asChild ? Slot.Root : "button"

  return (
    <Comp
      data-slot="button"
      data-variant={variant}
      data-size={size}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
