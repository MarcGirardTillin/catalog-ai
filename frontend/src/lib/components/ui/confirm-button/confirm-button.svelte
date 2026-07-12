<script lang="ts">
	// Bouton à confirmation en deux temps : le premier clic « arme » le bouton
	// (variante destructive + libellé de confirmation), le second déclenche
	// l'action ; l'armement retombe seul après timeoutMs. Factorise le pattern
	// dupliqué des suppressions (profils, tarifs, instructions, écartés).
	import type { ButtonSize, ButtonVariant } from "../button/button.svelte";
	import { Button } from "../button";

	let {
		onconfirm,
		label,
		confirmLabel = "Confirmer ?",
		variant = "ghost",
		size = "sm",
		disabled = false,
		timeoutMs = 3000,
		class: className,
	}: {
		onconfirm: () => void;
		label: string;
		confirmLabel?: string;
		variant?: ButtonVariant;
		size?: ButtonSize;
		disabled?: boolean;
		timeoutMs?: number;
		class?: string;
	} = $props();

	let arming = $state(false);
	let timer: ReturnType<typeof setTimeout> | undefined;

	// Désarme si le bouton disparaît ou est désactivé entre les deux clics.
	$effect(() => () => clearTimeout(timer));

	function onclick() {
		if (!arming) {
			arming = true;
			clearTimeout(timer);
			timer = setTimeout(() => (arming = false), timeoutMs);
			return;
		}
		clearTimeout(timer);
		arming = false;
		onconfirm();
	}
</script>

<Button
	{size}
	variant={arming ? "destructive" : variant}
	{disabled}
	class={className}
	{onclick}
>
	{arming ? confirmLabel : label}
</Button>
