"""
briefing_config.py - Perguntas do briefing de prospeccao, editaveis sem mexer em logica.
"""

BRIEFING_QUESTIONS = [
    {
        "key": "segmento",
        "label": "Qual segmento ou tipo de industria de alimentos voce quer atingir?",
        "exemplo": "chocolate, panificacao, bebidas, snacks",
        "required": True,
    },
    {
        "key": "aplicacao",
        "label": "Qual aplicacao ou tipo de produto o ingrediente entraria?",
        "exemplo": "recheio, cobertura, mix de cereais",
        "required": True,
    },
    {
        "key": "quantidade",
        "label": "Quantas empresas voce quer que a Manus traga nessa lista?",
        "exemplo": "20, 50, 100",
        "required": True,
    },
    {
        "key": "profundidade_pesquisa",
        "label": "Quer que a Manus faca uma pesquisa profunda pra confirmar que a empresa "
                  "realmente usa frutas ou vegetais desidratados, ou pode ser uma busca "
                  "mais ampla por todo o segmento?",
        "exemplo": "profunda (confirmar uso do ingrediente) / ampla (todo o segmento)",
        "required": True,
    },
    {
        "key": "tipo_empresa",
        "label": "A lista deve trazer so matrizes, ou tambem filiais?",
        "exemplo": "so matriz / matriz e filiais",
        "required": True,
    },
    {
        "key": "regiao",
        "label": "Alguma regiao ou estado especifico? (opcional)",
        "exemplo": "Sul, Nordeste, SP",
        "required": False,
    },
    {
        "key": "porte",
        "label": "Algum porte de empresa por faixa de faturamento ou numero de funcionarios? (opcional)",
        "exemplo": "pequena, media, grande",
        "required": False,
    },
    {
        "key": "look_alike",
        "label": "Quer buscar empresas parecidas com algum cliente especifico que voce ja tem? (opcional)",
        "exemplo": "nome do cliente de referencia",
        "required": False,
    },
]
