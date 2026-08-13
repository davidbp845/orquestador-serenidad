import type { Mensaje } from './useChatStream';

interface Props {
  mensaje: Mensaje;
}

export default function BurbujaMensaje({ mensaje }: Props) {
  const esUsuario = mensaje.rol === 'usuario';
  const esError = mensaje.rol === 'error';

  const clases = [
    'max-w-[80%] whitespace-pre-wrap rounded-2xl px-(--spacing-fluid-xs) py-(--spacing-fluid-2xs) text-sm',
    esUsuario
      ? 'bg-(--color-acento) text-(--color-texto-sobre-acento)'
      : esError
        ? 'border border-red-200 bg-red-50 text-red-700'
        : 'border border-(--color-borde) bg-(--color-superficie) text-(--color-texto)',
  ].join(' ');

  return (
    <div class={`flex ${esUsuario ? 'justify-end' : 'justify-start'}`}>
      <div class={clases}>
        {mensaje.texto || ' '}
      </div>
    </div>
  );
}
