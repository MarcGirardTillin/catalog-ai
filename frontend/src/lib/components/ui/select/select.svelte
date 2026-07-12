<script lang="ts">
	import type { Snippet } from "svelte";
	import type { HTMLSelectAttributes } from "svelte/elements";
	import { cn, type WithElementRef } from "@/lib/utils.js";

	let {
		ref = $bindable(null),
		value = $bindable(),
		class: className,
		children,
		...restProps
	}: WithElementRef<HTMLSelectAttributes> & { children?: Snippet } = $props();
</script>

<select
	bind:this={ref}
	bind:value
	data-slot="select"
	class={cn(
		"border-input bg-card text-foreground focus-visible:border-ring focus-visible:ring-ring/50 h-9 w-full min-w-0 cursor-pointer rounded-md border px-2.5 text-sm transition-colors outline-none focus-visible:ring-1 disabled:pointer-events-none disabled:opacity-50",
		className
	)}
	{...restProps}
>
	{@render children?.()}
</select>
