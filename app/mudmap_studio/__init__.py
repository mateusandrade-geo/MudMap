"""MudMap Studio — inspeção e edição da segmentação mineral por EDS.

Abre um pacote .mudmap (uma amostra/sítio) ou importa direto das pastas do projeto.
Fase 1: formato .mudmap + modo Inspetor.
Fase 2: camadas e visualizações de EDS (elementos aditivos, RGB, canais derivados das regras,
        contraste com histograma, contorno, clusters, composição em segundo plano).
Fase 3: modo Edição (substitui o napari): pincel, borracha, balde, conta-gotas, remover grão,
        retângulo/elipse/polígono/laço (pintar/apagar/reatribuir c/ filtro químico), pontos→regiões,
        propagar com revisão, morfologia, limpeza fora da amostra, desfazer/refazer, salvar com
        versões e exportar para estado/.
Fase 4: modo Segmentar: candidato pelas regras da config (regra/mapa/grupos/cluster, parâmetros
        ao vivo, idêntico ao segmentar.py), comparação com o rotulado (IoU/Dice/TP-FP-FN),
        calibração (comparar.py --calibrar), commit desfazível, gravar parâmetros na config
        (comentários preservados) e k-means (reconhecer.py).
Fase 5: modo Relatório (= relatorio_final.py, refeito após cada edição): Shepard, diâmetros, Na-K-Ca,
        composição mineral × elemento e tabela por mineral, com destaque no canvas; exportação PNG/SVG/
        JSON/CSV e inspetor HTML; comparação de vários .mudmap por campo ou por sítio.
"""
__version__ = "0.5.0"
FASE = 5
