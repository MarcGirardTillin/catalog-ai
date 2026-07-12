<script lang="ts" generics="K extends string">
	// Barre d'onglets sobre (bordure basse + trait actif) — factorise le
	// pattern dupliqué des pages Réglages / Paramètres / Produits. Les
	// panneaux restent à la charge de la page (souvent montés en `hidden`
	// pour conserver les saisies en cours).
	import { cn } from "@/lib/utils.js";

	let {
		tabs,
		value = $bindable(),
		label,
		class: className,
	}: {
		tabs: readonly { key: K; label: string }[];
		value: K;
		label?: string;
		class?: string;
	} = $props();
</script>

<div
	class={cn("border-border flex gap-4 border-b", className)}
	role="tablist"
	aria-label={label}
>
	{#each tabs as t (t.key)}
		<button
			type="button"
			role="tab"
			aria-selected={value === t.key}
			class="-mb-px cursor-pointer border-b-2 px-1 pb-2 text-sm font-medium transition-colors {value ===
			t.key
				? 'border-primary text-foreground'
				: 'text-muted-foreground hover:text-foreground border-transparent'}"
			onclick={() => (value = t.key)}
		>
			{t.label}
		</button>
	{/each}
</div>
