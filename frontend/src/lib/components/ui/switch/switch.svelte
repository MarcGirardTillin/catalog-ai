<script lang="ts">
	// Interrupteur accessible (bouton role="switch") pour les réglages
	// booléens. Un <label for> pointant sur son id lui relaie le clic
	// (les <button> sont des éléments labellisables).
	import { cn } from "@/lib/utils.js";

	let {
		checked = $bindable(false),
		disabled = false,
		id,
		class: className,
		onchange,
		"aria-label": ariaLabel,
	}: {
		checked?: boolean;
		disabled?: boolean;
		id?: string;
		class?: string;
		onchange?: (checked: boolean) => void;
		"aria-label"?: string;
	} = $props();

	function toggle() {
		checked = !checked;
		onchange?.(checked);
	}
</script>

<button
	type="button"
	role="switch"
	aria-checked={checked}
	aria-label={ariaLabel}
	{id}
	{disabled}
	data-slot="switch"
	class={cn(
		"focus-visible:ring-ring/50 inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border border-transparent transition-colors outline-none focus-visible:ring-2 disabled:pointer-events-none disabled:opacity-50",
		checked ? "bg-primary" : "bg-input",
		className
	)}
	onclick={toggle}
>
	<span
		class="bg-background pointer-events-none block size-4 rounded-full shadow-sm transition-transform {checked
			? 'translate-x-4'
			: 'translate-x-0.5'}"
	></span>
</button>
