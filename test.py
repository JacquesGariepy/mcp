import asyncio
from typing import Optional, Dict, Any
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from anthropic import Anthropic
import json
import os
from dotenv import load_dotenv

load_dotenv()  # charge les variables d'environnement depuis .env

class CodeAssistantClient:
    """
    Client pour interagir avec le serveur CodeAssistant via MCP.
    """
    def __init__(self):
        """Initialise le client CodeAssistant."""
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.anthropic = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        print("CodeAssistant Client initialisé.")
        
    async def connect_to_server(self, server_script_path: str):
        """
        Connecte le client au serveur CodeAssistant.
        
        Args:
            server_script_path: Chemin vers le script du serveur
        """
        # Vérification de l'extension du fichier pour déterminer le langage
        is_python = server_script_path.endswith('.py')
        
        if not is_python:
            raise ValueError("Le script serveur doit être un fichier .py")

        # Configuration des paramètres du serveur
        server_params = StdioServerParameters(
            command="python",
            args=[server_script_path],
            env=None
        )
        print("StdioServerParameters configurés pour le serveur:", server_params)

        # Établissement de la connexion au serveur
        stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
        self.stdio, self.write = stdio_transport
        self.session = await self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write))

        # Initialisation de la session
        await self.session.initialize()

        # Liste des outils disponibles
        response = await self.session.list_tools()
        tools = response.tools
        print("\nConnecté au serveur avec les outils:", [tool.name for tool in tools])
    
    async def analyze_project(self, project_dir: str) -> str:
        """
        Analyse un projet et génère un rapport.
        
        Args:
            project_dir: Chemin vers le répertoire du projet
            
        Returns:
            Rapport d'analyse du projet
        """
        # Récupération de la structure du projet
        project_tree_json = await self.session.call_tool("get_project_tree", {"directory": project_dir})
        project_tree = json.loads(project_tree_json.content[0].text)
        
        # Recherche de fichiers Python
        files_json = await self.session.call_tool("list_files", {
            "directory": project_dir,
            "pattern": "**/*.py"
        })
        files_data = json.loads(files_json.content[0].text)
        
        # Analyse de chaque fichier Python
        analyses = []
        for file_path in files_data.get("files", [])[:5]:  # Limité aux 5 premiers fichiers pour cet exemple
            analysis_json = await self.session.call_tool("analyze_code", {"file_path": file_path})
            analysis = json.loads(analysis_json.content[0].text)
            analyses.append(analysis)
            
        # Construction du contexte pour Claude
        context = {
            "project_structure": project_tree,
            "file_analyses": analyses
        }
        
        # Demande à Claude de générer un rapport
        response = self.anthropic.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=2000,
            messages=[
                {
                    "role": "user", 
                    "content": f"""En tant qu'expert en développement Python, analyse les informations suivantes sur un projet 
                    et génère un rapport détaillé incluant:
                    
                    1. Structure globale du projet
                    2. Qualité du code (couverture de docstrings, complexité apparente)
                    3. Recommandations d'amélioration
                    4. Évaluation générale
                    
                    Voici les données d'analyse:
                    {json.dumps(context, indent=2)}
                    """
                }
            ]
        )
        
        return response.content[0].text
    
    async def improve_code(self, file_path: str) -> str:
        """
        Suggère des améliorations pour un fichier de code.
        
        Args:
            file_path: Chemin vers le fichier à améliorer
            
        Returns:
            Suggestions d'amélioration du code
        """
        # Récupération du contenu du fichier
        file_content = await self.session.call_tool("get_file", {"file_path": file_path})
        content = file_content.content[0].text
        
        # Analyse du fichier
        analysis_json = await self.session.call_tool("analyze_code", {"file_path": file_path})
        analysis = json.loads(analysis_json.content[0].text)
        
        # Demande d'amélioration à Claude
        response = self.anthropic.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=2000,
            messages=[
                {
                    "role": "user", 
                    "content": f"""En tant qu'expert Python, suggère des améliorations pour ce code.
                    
                    Fichier: {file_path}
                    
                    Contenu:
                    ```python
                    {content}
                    ```
                    
                    Analyse:
                    {json.dumps(analysis, indent=2)}
                    
                    Propose des améliorations concrètes concernant:
                    1. La lisibilité
                    2. La performance
                    3. Les bonnes pratiques Python
                    4. La documentation
                    
                    Si possible, suggère une version améliorée du code.
                    """
                }
            ]
        )
        
        return response.content[0].text
    
    async def update_docstrings(self, file_path: str) -> Dict[str, Any]:
        """
        Ajoute ou améliore les docstrings dans un fichier Python.
        
        Args:
            file_path: Chemin vers le fichier à documenter
            
        Returns:
            Résultats de la mise à jour des docstrings
        """
        # Récupération du contenu du fichier
        file_content = await self.session.call_tool("get_file", {"file_path": file_path})
        original_content = file_content.content[0].text
        
        # Analyse du fichier
        analysis_json = await self.session.call_tool("analyze_code", {"file_path": file_path})
        analysis = json.loads(analysis_json.content[0].text)
        
        # Trouve les fonctions et classes sans docstrings
        items_without_docstrings = []
        
        for function in analysis.get("functions", []):
            if function["docstring"] == "No docstring":
                items_without_docstrings.append({
                    "type": "function",
                    "name": function["name"],
                    "line": function["lineno"]
                })
                
        for class_def in analysis.get("classes", []):
            if class_def["docstring"] == "No docstring":
                items_without_docstrings.append({
                    "type": "class",
                    "name": class_def["name"],
                    "line": class_def["lineno"]
                })
                
            for method in class_def.get("methods", []):
                if method["docstring"] == "No docstring":
                    items_without_docstrings.append({
                        "type": "method",
                        "name": f"{class_def['name']}.{method['name']}",
                        "line": method["lineno"]
                    })
        
        # Si aucun élément ne nécessite de docstring, retourne
        if not items_without_docstrings:
            return {
                "status": "success",
                "message": "Tous les éléments ont déjà des docstrings",
                "updated_items": []
            }
            
        # Contenu mis à jour
        updated_content = original_content
        updated_items = []
        
        # Pour chaque élément sans docstring
        for item in items_without_docstrings:
            # Génère une docstring
            docstring_json = await self.session.call_tool("generate_docstring", {
                "file_path": file_path,
                "object_name": item["name"].split(".")[-1],
                "line_number": item["line"]
            })
            
            docstring_data = json.loads(docstring_json.content[0].text)
            
            if docstring_data.get("success", False):
                updated_items.append({
                    "name": item["name"],
                    "docstring": docstring_data["suggested_docstring"]
                })
        
        # Demande à Claude d'intégrer les docstrings dans le code
        if updated_items:
            response = self.anthropic.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=4000,
                messages=[
                    {
                        "role": "user", 
                        "content": f"""Ton tâche est d'ajouter des docstrings au code Python suivant.
                        
                        Code original:
                        ```python
                        {original_content}
                        ```
                        
                        Voici les docstrings à ajouter:
                        {json.dumps(updated_items, indent=2)}
                        
                        Retourne uniquement le code mis à jour avec les docstrings ajoutées aux bons endroits.
                        N'ajoute pas de commentaires ou d'explications.
                        """
                    }
                ]
            )
            
            # Extrait le code mis à jour
            updated_content = response.content[0].text
            
            # Si le contenu est entouré de triple backticks, les supprime
            if "```python" in updated_content and "```" in updated_content:
                updated_content = updated_content.split("```python")[1].split("```")[0].strip()
            
            # Mise à jour du fichier
            update_result = await self.session.call_tool("update_file", {
                "file_path": file_path,
                "content": updated_content
            })
            
            update_data = json.loads(update_result.content[0].text)
            
            if update_data.get("success", False):
                return {
                    "status": "success",
                    "message": f"Docstrings ajoutées pour {len(updated_items)} éléments",
                    "updated_items": updated_items
                }
            else:
                return {
                    "status": "error",
                    "message": "Échec de la mise à jour du fichier",
                    "error": update_data.get("message", "Erreur inconnue")
                }
        
        return {
            "status": "info",
            "message": "Aucune docstring n'a été générée",
            "updated_items": []
        }
    
    async def generate_file(self, project_dir: str, file_path: str, description: str) -> Dict[str, Any]:
        """
        Génère un nouveau fichier de code basé sur une description.
        
        Args:
            project_dir: Répertoire du projet
            file_path: Chemin relatif du fichier à créer
            description: Description des fonctionnalités à implémenter
            
        Returns:
            Résultat de la génération du fichier
        """
        # Récupération de la structure du projet pour contexte
        project_tree_json = await self.session.call_tool("get_project_tree", {"directory": project_dir})
        project_tree = json.loads(project_tree_json.content[0].text)
        
        # Chemin absolu du fichier
        abs_file_path = os.path.join(project_dir, file_path)
        
        # Vérification si le fichier existe déjà
        file_exists = os.path.exists(abs_file_path)
        if file_exists:
            return {
                "status": "error",
                "message": f"Le fichier {file_path} existe déjà"
            }
            
        # Détermine le type de fichier à partir de l'extension
        file_ext = os.path.splitext(file_path)[1].lower()
        
        # Initialisation des variables pour la génération
        language = ""
        prompt_template = ""
        
        # Configuration selon le type de fichier
        if file_ext == '.py':
            language = "Python"
            prompt_template = """En tant qu'expert Python, génère un fichier Python suivant cette description:
            
            Description: {description}
            
            Structure du projet:
            {project_structure}
            
            Assure-toi que le code:
            1. Respecte les bonnes pratiques Python (PEP 8)
            2. Inclut des docstrings complètes
            3. Gère correctement les erreurs
            4. Est bien structuré et modulaire
            
            Retourne uniquement le code Python sans explications.
            """
        elif file_ext in ['.js', '.ts']:
            language = "JavaScript/TypeScript"
            prompt_template = """En tant qu'expert JavaScript/TypeScript, génère un fichier suivant cette description:
            
            Description: {description}
            Type de fichier: {file_type}
            
            Structure du projet:
            {project_structure}
            
            Assure-toi que le code:
            1. Respecte les bonnes pratiques modernes
            2. Est bien documenté
            3. Gère correctement les erreurs
            4. Est bien structuré
            
            Retourne uniquement le code sans explications.
            """
        elif file_ext in ['.html', '.css']:
            language = "HTML/CSS"
            prompt_template = """En tant qu'expert web, génère un fichier {file_type} suivant cette description:
            
            Description: {description}
            
            Structure du projet:
            {project_structure}
            
            Assure-toi que le code:
            1. Est valide et conforme aux standards
            2. Est responsive si applicable
            3. Est bien documenté avec des commentaires
            4. Utilise des pratiques modernes
            
            Retourne uniquement le code sans explications.
            """
        else:
            language = "texte"
            prompt_template = """Génère un fichier texte suivant cette description:
            
            Description: {description}
            
            Structure du projet:
            {project_structure}
            
            Retourne uniquement le contenu du fichier sans explications.
            """
        
        # Formatage du prompt
        prompt = prompt_template.format(
            description=description,
            file_type=file_ext,
            project_structure=json.dumps(project_tree, indent=2)
        )
        
        # Demande à Claude de générer le contenu
        response = self.anthropic.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}]
        )
        
        generated_content = response.content[0].text
        
        # Si le contenu est entouré de triple backticks, les supprime
        if "```" in generated_content:
            code_blocks = re.findall(r"```(?:\w+)?\n([\s\S]+?)\n```", generated_content)
            if code_blocks:
                generated_content = code_blocks[0]
        
        # Création du fichier
        create_result = await self.session.call_tool("create_file", {
            "file_path": abs_file_path,
            "content": generated_content
        })
        
        create_data = json.loads(create_result.content[0].text)
        
        if create_data.get("success", False):
            return {
                "status": "success",
                "message": f"Fichier {file_path} créé avec succès",
                "file_path": abs_file_path,
                "language": language
            }
        else:
            return {
                "status": "error",
                "message": "Échec de la création du fichier",
                "error": create_data.get("message", "Erreur inconnue")
            }
    
    async def cleanup(self):
        """Nettoie les ressources utilisées par le client."""
        await self.exit_stack.aclose()

async def main():
    """Fonction principale pour exécuter le client."""
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python client.py <path_to_server_script>")
        sys.exit(1)
    
    server_script_path = sys.argv[1]
    project_dir = input("Chemin du projet à analyser: ")
    
    client = CodeAssistantClient()
    print("Démarrage du client CodeAssistant...")
    try:
        await client.connect_to_server(server_script_path)
        
        while True:
            print("\n--- CodeAssistant Menu ---")
            print("1. Analyser le projet")
            print("2. Améliorer un fichier de code")
            print("3. Mettre à jour les docstrings d'un fichier")
            print("4. Générer un nouveau fichier")
            print("5. Quitter")
            
            choice = input("\nChoix: ")
            
            if choice == "1":
                print("\nAnalyse du projet en cours...")
                report = await client.analyze_project(project_dir)
                print("\n=== Rapport d'analyse ===")
                print(report)
                
            elif choice == "2":
                file_path = input("Chemin du fichier à améliorer: ")
                print("\nAnalyse et amélioration du code en cours...")
                improvements = await client.improve_code(file_path)
                print("\n=== Suggestions d'amélioration ===")
                print(improvements)
                
            elif choice == "3":
                file_path = input("Chemin du fichier pour mise à jour des docstrings: ")
                print("\nMise à jour des docstrings en cours...")
                result = await client.update_docstrings(file_path)
                print(f"\nStatut: {result['status']}")
                print(f"Message: {result['message']}")
                if result['status'] == "success":
                    print(f"Éléments mis à jour: {len(result['updated_items'])}")
                
            elif choice == "4":
                rel_path = input("Chemin relatif du fichier à créer (depuis le répertoire du projet): ")
                description = input("Description des fonctionnalités: ")
                print("\nGénération du fichier en cours...")
                result = await client.generate_file(project_dir, rel_path, description)
                print(f"\nStatut: {result['status']}")
                print(f"Message: {result['message']}")
                
            elif choice == "5":
                break
                
            else:
                print("Choix invalide. Veuillez réessayer.")
                
    finally:
        await client.cleanup()

if __name__ == "__main__":
    import re
    asyncio.run(main())
