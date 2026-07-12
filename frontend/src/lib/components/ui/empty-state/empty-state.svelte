<script lang="ts">
	// État vide standard : carte centrée avec message et action optionnelle.
	import type { Snippet } from "svelte";
	import { Card, CardContent } from "../card";

	let {
		message,
		children,
		class: className,
	}: { message: string; children?: Snippet; class?: string } = $props();
</script>

<Card class={className}>
	<CardContent class="flex flex-col items-center gap-3 py-8 text-center">
		<p class="text-muted-foreground text-sm">{message}</p>
		{@render children?.()}
	</CardContent>
</Card>
