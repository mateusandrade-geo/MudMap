"""Ponto de entrada: python -m mudmap_studio [arquivo.mudmap | --exemplo]"""
import sys
from pathlib import Path


def autoteste(jan, app, arquivo, saida, raiz_projeto=None):
    """Verificação do build: abre o .mudmap, importa do projeto (se dado) e captura a janela.
    Escreve <saida>.log com o resultado; usado para validar o .exe sem interação."""
    import time
    import traceback

    from .nucleo import importar, objetos, pacote
    log = []
    ok = True
    try:
        t = time.time()
        am = pacote.abrir(arquivo)
        ob = objetos.calcular(am, 3)
        jan._carregado((am, ob), Path(arquivo))
        jan.aguardar_render()
        log.append(f"abrir+objetos+render OK {time.time() - t:.2f}s  n={ob.n}  shape={am.shape}  "
                   f"clusters={'sim' if am.clusters is not None else 'não'}")
        jan.grab().save(str(saida))
        t = time.time()                          # fase 2: canal derivado suavizado + contorno
        jan.camadas.seg_estilo.set("contorno")
        jan.camadas.set_modo_fundo("canal")
        jan.camadas.sl_raio.setValue(27)
        jan.aguardar_render()
        if jan.camadas.erro_canal.isVisible():
            raise RuntimeError("canal: " + jan.camadas.erro_canal.text())
        log.append(f"canal {jan._visual.canal_expr} r={jan._visual.canal_raio} OK {time.time() - t:.2f}s")
        jan.grab().save(str(saida).replace(".png", "_canal.png"))
        # fase 3: operações de edição (exercita os módulos carregados sob demanda no .exe)
        import numpy as np
        t = time.time()
        jan.set_modo("edicao")
        ed = jan.controle.editor
        orig = am.rotulos.copy()
        ids, cont = np.unique(am.rotulos[am.rotulos > 0], return_counts=True)
        mid = int(ids[np.argmax(cont)])
        h, w = am.shape
        ed.forma("poligono", [(w * .1, h * .1), (w * .3, h * .12), (w * .25, h * .3)], "pintar", mid)
        ed.forma("elipse", [(w * .5, h * .5), (w * .6, h * .58)], "apagar", mid, filtro_txt="Si>0.1")
        ys, xs = np.nonzero(am.rotulos == mid)
        ed.balde(int(xs[0]), int(ys[0]), mid)
        ed.pontos([(w * .7, h * .7), (w * .72, h * .7), (w * .71, h * .73)], mid, eps=w * .05)
        ed.pontos([(w * .2, h * .8), (w * .23, h * .8), (w * .22, h * .83)], mid, eps=w * .05, modo="convexo")
        ed.morfologia(mid, "convexo")
        ed.morfologia(mid, "limpar", am.area_min)
        lab, n, _info = ed.propagar(mid)
        while ed.desfazer():
            pass
        if not (am.rotulos == orig).all():
            raise RuntimeError("desfazer tudo não voltou ao original")
        jan.set_modo("inspetor")
        jan.aguardar_render()
        log.append(f"edição (polígono, elipse+filtro, balde, pontos, morfologia, propagar={n}, "
                   f"desfazer tudo) OK {time.time() - t:.2f}s")
        # fase 4: segmentar (candidatos = pipeline), k-means (sklearn), gravação da config
        from .nucleo import config_texto
        from .nucleo import segmentacao as sg
        t = time.time()
        jan.set_modo("segmentar")
        jan.aguardar_render()
        ious = []
        for mid in [int(v) for v in np.unique(am.rotulos) if v]:
            try:
                cand, _i = sg.candidato(am, mid, sg.params_da_regra(am, mid), substituir=True)
            except ValueError:
                continue
            ious.append(f"{am.mineral(mid).nome}={sg.comparar(am.rotulos == mid, cand)['iou']:.3f}")
        _lab, info = sg.kmeans(am, 9, 4)
        if am.config_yaml:
            pr = {k: v for k, v in sg.params_da_regra(am, mid).items() if k in sg.CHAVES_REGRA}
            config_texto.substituir(am.config_yaml, am.mineral(mid).nome, pr, am.pixel_um)
        jan.set_modo("inspetor")
        jan.aguardar_render()
        log.append(f"segmentar: IoU {' '.join(ious)} · k-means {len(info['nomes'])} clusters · "
                   f"config OK · {time.time() - t:.2f}s")
        # fase 5: relatório (QPainter), PNG/SVG (QtSvg), JSON/CSV, inspetor HTML (template embutido no .exe)
        # e comparação por sítio (resumo de outro .mudmap na thread) — lista da comparação restaurada no fim
        import tempfile

        from PyQt6.QtCore import QSettings

        from .nucleo import relatorio
        t = time.time()
        jan.set_modo("relatorio")
        jan.aguardar_render(120)
        R = jan.rel.R
        if R is None or jan.versao_stats != jan.controle.editor.versao:
            raise RuntimeError("relatório não calculado / grãos desatualizados")
        jan.grab().save(str(saida).replace(".png", "_relatorio.png"))
        pasta = Path(tempfile.mkdtemp(prefix="mudmap_autoteste_"))
        for k, ext in (("png", "png"), ("svg", "svg"), ("json", "json"), ("csv_minerais", "csv"),
                       ("csv_graos", "csv"), ("html", "html")):
            c = jan.rel.exportar(k, pasta / f"rel_{k}.{ext}")
            jan.aguardar_render(120)                      # CSV de grãos e HTML rodam em segundo plano
            if c is None or not c.exists() or not c.stat().st_size:
                raise RuntimeError(f"exportar {k} falhou")
        cfg = QSettings("MudMap", "Studio")
        lista_antes = cfg.value("comparar/arquivos", []) or []
        try:
            b = pacote.abrir(arquivo)
            b.sitio = f"{relatorio.grupo_sitio(am.sitio)}.9"
            arq2 = pasta / f"campo_{b.sitio}.mudmap"
            pacote.salvar(b, arq2)
            jan.rel.adicionar([str(arq2)])
            t2 = time.time()
            while jan.rel.ocupado() and time.time() - t2 < 180:
                app.processEvents()
                time.sleep(0.02)
            ag = relatorio.agregar(jan.rel._compactos(), "sitio")
        finally:
            cfg.setValue("comparar/arquivos", lista_antes)
            jan.rel.arquivos = [lista_antes] if isinstance(lista_antes, str) else list(lista_antes)
        if len(ag) != 1 or ag[0]["n_campos"] != 2:
            raise RuntimeError(f"comparação por sítio: esperado 1 sítio com 2 campos, veio {len(ag)}")
        jan.set_modo("inspetor")
        jan.aguardar_render()
        log.append(f"relatório: {R.resumo['n_graos']} grãos · {R.resumo['fracoes_area']} · Shepard "
                   f"{R.resumo['classe_shepard']} · exportou png/svg/json/csv/html · comparação por sítio "
                   f"(2 campos) OK · {time.time() - t:.2f}s")
        t = time.time()                          # exemplo sintético (config embutida nos recursos do .exe)
        from .nucleo import exemplo
        with tempfile.TemporaryDirectory(prefix="mudmap_exemplo_") as d:
            rx = exemplo.gerar_projeto(Path(d) / "exemplo", tamanho=320)
            obx = objetos.calcular(importar.importar_sitio(next(x for x in importar.listar_sitios(rx) if x.ativo)), 3)
        log.append(f"exemplo sintético (gerar + importar) OK {time.time() - t:.2f}s  n={obx.n}")
        if raiz_projeto:
            t = time.time()
            f = next(x for x in importar.listar_sitios(raiz_projeto) if x.ativo)
            am2 = importar.importar_sitio(f)
            ob2 = objetos.calcular(am2, 3)
            log.append(f"importar sítio {f.sitio} OK {time.time() - t:.2f}s  n={ob2.n}  "
                       f"máscara={int(am2.mascara.sum())}")
    except Exception:
        ok = False
        log.append(traceback.format_exc())
    Path(str(saida) + ".log").write_text("\n".join(log) + f"\nRESULTADO: {'OK' if ok else 'FALHOU'}\n",
                                          encoding="utf-8")
    return 0 if ok else 1


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    teste = None
    if "--autoteste" in argv:            # --autoteste <arquivo.mudmap> <saida.png> [raiz_projeto]
        i = argv.index("--autoteste")
        teste = argv[i + 1:i + 4]
        argv = argv[:i]
    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import QApplication

    from .ui import tema
    from .ui.janela import JanelaPrincipal

    app = QApplication(argv)
    app.setApplicationName("MudMap Studio")
    app.setOrganizationName("MudMap")
    ico = Path(__file__).resolve().parent / "recursos" / "mudmap.ico"   # também no .exe (dados do pacote)
    if ico.exists():
        app.setWindowIcon(QIcon(str(ico)))
    tema.aplicar(app)
    jan = JanelaPrincipal()
    jan.show()
    if teste:
        return autoteste(jan, app, teste[0], teste[1], teste[2] if len(teste) > 2 else None)
    arquivos = [a for a in argv[1:] if a.lower().endswith(".mudmap") and Path(a).exists()]
    if arquivos:
        jan.abrir_arquivo(arquivos[0])
    elif "--exemplo" in argv:
        jan.abrir_exemplo()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
