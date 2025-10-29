let mangaId = null;

const loader = () => document.getElementById('loader');
const mensajeEstado = () => document.getElementById('mensajeEstado');
const tituloManga = () => document.getElementById('tituloManga');
const progresoManga = () => document.getElementById('progresoManga');
const ultimoCapituloManga = () => document.getElementById('ultimoCapituloManga');
const enlaceManga = () => document.getElementById('enlaceManga');
const resumenTotal = () => document.getElementById('resumenTotal');
const resumenDescargados = () => document.getElementById('resumenDescargados');
const resumenPendientes = () => document.getElementById('resumenPendientes');
const resumenUltimo = () => document.getElementById('resumenUltimo');
const tablaDescargas = () => document.getElementById('tablaDescargas');
const mensajeVacio = () => document.getElementById('mensajeVacio');

const mostrarLoader = (visible) => {
  const nodoLoader = loader();
  if (!nodoLoader) return;
  nodoLoader.style.display = visible ? 'flex' : 'none';
};

const mostrarMensaje = (texto, tipo = 'warning') => {
  const nodoMensaje = mensajeEstado();
  if (!nodoMensaje) return;
  nodoMensaje.textContent = texto;
  nodoMensaje.classList.remove('d-none', 'alert-warning', 'alert-danger', 'alert-info', 'alert-success');
  nodoMensaje.classList.add(`alert-${tipo}`);
};

const ocultarMensaje = () => {
  const nodoMensaje = mensajeEstado();
  if (!nodoMensaje) return;
  nodoMensaje.classList.add('d-none');
  nodoMensaje.textContent = '';
};

const formatearProgreso = (capituloActual, ultimoCapitulo) => {
  const actualNumero = parseFloat(capituloActual);
  const ultimoNumero = parseFloat(ultimoCapitulo);
  const actualTexto = Number.isFinite(actualNumero)
    ? (Number.isInteger(actualNumero) ? actualNumero : actualNumero.toFixed(1))
    : String(capituloActual || '-');
  const ultimoTexto = Number.isFinite(ultimoNumero)
    ? (Number.isInteger(ultimoNumero) ? ultimoNumero : ultimoNumero.toFixed(1))
    : String(ultimoCapitulo || '-');
  return `${actualTexto} / ${ultimoTexto}`;
};

const actualizarCabecera = (manga) => {
  if (!manga) return;
  tituloManga().textContent = manga.nombre || 'Descargas';
  progresoManga().textContent = formatearProgreso(
    manga.capitulo_actual,
    manga.ultimo_capitulo
  );
  ultimoCapituloManga().textContent =
    manga.ultimo_capitulo !== undefined && manga.ultimo_capitulo !== null
      ? manga.ultimo_capitulo
      : '-';
  if (manga.url) {
    enlaceManga().href = manga.url;
  }
};

const actualizarResumen = (resumen) => {
  const total = resumen?.total ?? 0;
  const descargados = resumen?.descargados ?? 0;
  const pendientes = resumen?.pendientes ?? 0;
  resumenTotal().textContent = total;
  resumenDescargados().textContent = descargados;
  resumenPendientes().textContent = pendientes;
  resumenUltimo().textContent = resumen?.ultimo_descargado || '-';
};

const construirFilaDescarga = (capitulo) => {
  const fila = document.createElement('tr');
  fila.setAttribute('data-capitulo-id', capitulo.id);
  const nombre = capitulo.nombre || 'Capítulo';
  const numero = capitulo.numero ? `Capítulo ${capitulo.numero}` : '';

  const enlaceHtml = capitulo.enlace
    ? `<a href="${capitulo.enlace}" target="_blank" rel="noopener noreferrer">Abrir enlace</a>`
    : '<span class="text-muted">Sin enlace</span>';

  const checkboxId = `descarga_${capitulo.id}`;
  const marcado = capitulo.descargado ? 'checked' : '';
  const etiquetaEstado = capitulo.descargado ? 'Sí' : 'No';

  fila.innerHTML = `
    <td>
      <div class="fw-semibold">${nombre}</div>
      ${
        numero
          ? `<div class="text-muted small mb-1">${numero}</div>`
          : ''
      }
      ${
        capitulo.fecha_descarga
          ? `<div class="text-muted small">Descargado: ${new Date(
              capitulo.fecha_descarga
            ).toLocaleString()}</div>`
          : ''
      }
    </td>
    <td>${enlaceHtml}</td>
    <td class="text-center">
      <div class="form-check d-inline-flex align-items-center gap-2 justify-content-center">
        <input class="form-check-input" type="checkbox" id="${checkboxId}" ${marcado} />
        <label class="form-check-label small mb-0" for="${checkboxId}">${etiquetaEstado}</label>
      </div>
    </td>
  `;

  const checkbox = fila.querySelector('input[type="checkbox"]');
  const label = fila.querySelector('label');
  if (checkbox) {
    checkbox.addEventListener('change', async (event) => {
      await actualizarEstadoDescarga(capitulo.id, event.target.checked, label, checkbox);
    });
  }

  return fila;
};

const renderizarTabla = (capitulos) => {
  const tbody = tablaDescargas();
  if (!tbody) return;
  tbody.innerHTML = '';

  const vacio = mensajeVacio();
  if (!Array.isArray(capitulos) || capitulos.length === 0) {
    if (vacio) {
      vacio.classList.remove('d-none');
    }
    return;
  }

  if (vacio) {
    vacio.classList.add('d-none');
  }
  capitulos.forEach((capitulo) => {
    tbody.appendChild(construirFilaDescarga(capitulo));
  });
};

const cargarDescargas = async () => {
  if (!mangaId) return;
  mostrarLoader(true);
  ocultarMensaje();
  try {
    const response = await fetch(`/manga/${mangaId}/descargas`);
    if (!response.ok) {
      throw new Error('No fue posible obtener las descargas.');
    }
    const data = await response.json();
    actualizarCabecera(data.manga);
    actualizarResumen(data.resumen);
    renderizarTabla(data.capitulos);
    if (!Array.isArray(data.capitulos) || data.capitulos.length === 0) {
      mostrarMensaje(
        'No se detectaron capítulos en el sitio origen para este manga. Revisa la URL o intenta más tarde.',
        'info'
      );
    }
  } catch (error) {
    console.error('Error al cargar descargas:', error);
    mostrarMensaje(
      error.message || 'Ocurrió un error al cargar las descargas.',
      'danger'
    );
    renderizarTabla([]);
  } finally {
    mostrarLoader(false);
  }
};

const actualizarEstadoDescarga = async (capituloId, marcado, etiqueta, checkbox) => {
  if (!capituloId) return;

  checkbox.disabled = true;
  etiqueta.textContent = marcado ? 'Sí' : 'No';

  try {
    const response = await fetch(`/descargas/${capituloId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ descargado: Boolean(marcado) }),
    });

    if (!response.ok) {
      throw new Error('No se pudo actualizar el estado de descarga.');
    }

    const data = await response.json();
    if (data?.resumen) {
      actualizarResumen(data.resumen);
    }
  } catch (error) {
    console.error('Error al actualizar descarga:', error);
    checkbox.checked = !marcado;
    etiqueta.textContent = checkbox.checked ? 'Sí' : 'No';
    mostrarMensaje(
      error.message || 'Error al actualizar el estado del capítulo.',
      'danger'
    );
  } finally {
    checkbox.disabled = false;
  }
};

const marcarTodoDescargado = async (boton) => {
  if (!mangaId) return;
  if (boton) boton.disabled = true;
  mostrarLoader(true);
  ocultarMensaje();

  try {
    const response = await fetch(`/manga/${mangaId}/descargas/marcar-todos`, {
      method: 'POST',
    });

    if (!response.ok) {
      throw new Error('No se pudo marcar todos los capítulos como descargados.');
    }

    const data = await response.json();
    if (data?.resumen) {
      actualizarResumen(data.resumen);
    }
    if (Array.isArray(data?.capitulos)) {
      renderizarTabla(data.capitulos);
    } else {
      renderizarTabla([]);
    }
    if (data?.mensaje) {
      mostrarMensaje(
        data.mensaje,
        data.actualizado ? 'info' : 'warning'
      );
    } else {
      ocultarMensaje();
    }
  } catch (error) {
    console.error('Error al marcar todo como descargado:', error);
    mostrarMensaje(
      error.message || 'Ocurrió un error al marcar todos los capítulos.',
      'danger'
    );
  } finally {
    if (boton) boton.disabled = false;
    mostrarLoader(false);
  }
};

const actualizarUrlDesdeDescargas = async (boton) => {
  if (!mangaId) return;
  const enlace = enlaceManga();
  const urlActual = enlace ? enlace.href : '';
  const nuevaUrl = window.prompt('Ingresa la nueva URL del manga:', urlActual);

  if (nuevaUrl === null) {
    return; // cancelado
  }

  const urlLimpia = nuevaUrl.trim();
  if (!urlLimpia) {
    mostrarMensaje('La URL no puede estar vacía.', 'warning');
    return;
  }

  if (boton) boton.disabled = true;
  mostrarLoader(true);
  ocultarMensaje();

  try {
    const response = await fetch(`/mangas/${mangaId}/url`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: urlLimpia }),
    });

    const data = await response.json().catch(() => null);

    if (!response.ok) {
      const mensaje = data?.error || 'No se pudo actualizar la URL.';
      mostrarMensaje(mensaje, 'danger');
      return;
    }

    if (data?.manga) {
      actualizarCabecera(data.manga);
      if (enlace) {
        enlace.href = data.manga.url || urlLimpia;
      }
    } else if (enlace) {
      enlace.href = urlLimpia;
    }

    mostrarMensaje(
      data?.mensaje || 'URL actualizada correctamente.',
      'success'
    );
  } catch (error) {
    console.error('Error al actualizar URL:', error);
    mostrarMensaje(
      'Ocurrió un error al actualizar la URL.',
      'danger'
    );
  } finally {
    mostrarLoader(false);
    if (boton) boton.disabled = false;
  }

  await cargarDescargas();
};

document.addEventListener('DOMContentLoaded', () => {
  const params = new URLSearchParams(window.location.search);
  mangaId = params.get('id');

  const refrescarBtn = document.getElementById('refrescarLista');
  if (refrescarBtn) {
    refrescarBtn.addEventListener('click', () => cargarDescargas());
  }

  const volverBtn = document.getElementById('volverListado');
  if (volverBtn) {
    volverBtn.addEventListener('click', (event) => {
      event.preventDefault();
      const destino = `/?fromDescargas=${encodeURIComponent(
        mangaId || ''
      )}&t=${Date.now()}`;
      window.location.href = destino;
    });
  }

  const marcarTodoBtn = document.getElementById('marcarTodoDescargado');
  if (marcarTodoBtn) {
    marcarTodoBtn.addEventListener('click', () =>
      marcarTodoDescargado(marcarTodoBtn)
    );
  }

  const actualizarUrlBtn = document.getElementById('actualizarUrlDescargas');
  if (actualizarUrlBtn) {
    actualizarUrlBtn.addEventListener('click', () =>
      actualizarUrlDesdeDescargas(actualizarUrlBtn)
    );
  }

  if (!mangaId) {
    mostrarMensaje('No se proporcionó el ID del manga.', 'danger');
    renderizarTabla([]);
    mostrarLoader(false);
    return;
  }

  cargarDescargas();
});
