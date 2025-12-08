"""
CrewAI Builder with Task Context Resolution
Converts JSON crew definitions to CrewAI objects with proper task chaining.

Created: Fresh implementation for task context chaining feature
Changes: 
- New file - implements critical two-pass task context resolution
- This is THE key component that fixes task-to-task content passing
- Added embedder parameter support for JWT-authenticated embeddings via LiteLLM proxy
"""

from typing import Dict, List, Optional
from crewai import Agent, Task, Crew, Process
from ivcap_service import getLogger

logger = getLogger("app.crew_builder")


class CrewBuilder:
    """
    Builds CrewAI Crew with proper task context resolution.
    
    The Challenge:
        JSON defines task context as strings: {"context": ["research_task"]}
        CrewAI expects Task objects: task.context = [research_task_object]
    
    The Solution:
        Two-pass building:
        1. Create all Agent and Task objects
        2. Resolve context string names → Task object references
    
    Usage:
        from service_types import Context, CrewA
        
        ctxt = Context(vectordb_config=..., job_id="...")
        builder = CrewBuilder(ctxt)
        crew = builder.build_crew(crew_spec, llm, job_id="...")
    """
    
    def __init__(self, context):
        """
        Initialize builder with runtime context.
        
        Args:
            context: Context object from service_types with:
                - vectordb_config: ChromaDB configuration
                - job_id: Job identifier
                - inputs_dir: Optional artifacts directory
                - jwt_token: Optional JWT for authentication
                - llm_factory: Optional LLM factory for per-agent models
        """
        self.context = context
    
    def build_agents(
        self, 
        agent_specs: List, 
        crew_llm
    ) -> Dict[str, Agent]:
        """
        Build all agents with optional per-agent LLM models.
        
        Args:
            agent_specs: List of AgentA spec objects
            crew_llm: Default LLM for crew (used if agent doesn't specify custom)
        
        Returns:
            Dictionary mapping agent name → Agent object
        
        Example:
            agent_specs = [
                AgentA(name="researcher", llm="gpt-4o", ...),
                AgentA(name="writer", ...)  # Uses crew_llm
            ]
            agents = builder.build_agents(agent_specs, default_llm)
            # agents["researcher"] has custom LLM
            # agents["writer"] has crew_llm
        """
        agents = {}
        
        for spec in agent_specs:
            # AgentA.as_crew_agent() handles:
            # - Creating Agent with tools
            # - Per-agent custom LLM if specified
            # - Fallback to crew_llm if custom fails
            agent = spec.as_crew_agent(
                ctxt=self.context,
                llm=crew_llm
            )
            agents[spec.name] = agent
            logger.debug(f"Built agent: {spec.name}")
        
        logger.info(f"Built {len(agents)} agents")
        return agents
    
    def build_tasks(
        self, 
        task_specs: List,
        agents: Dict[str, Agent]
    ) -> List[Task]:
        """
        Build tasks with TWO-PASS context resolution.
        
        Standard CrewAI Behavior (from docs):
        - Sequential process: "output of one task serving as context for the next"
        - Context expects list of Task objects: context=[task1, task2]
        
        Our JSON Format:
        - Tasks specify context as string names: "context": ["research_task"]
        - We resolve string names → Task object references
        - Empty/missing context → auto-chain to previous task (sequential default)
        
        Args:
            task_specs: List of TaskA spec objects
            agents: Dictionary of built Agent objects
        
        Returns:
            List of Task objects with resolved context chains
        
        Example:
            {
              "tasks": [
                {"name": "research_task", "agent": "researcher"},
                {"name": "write_task", "agent": "writer", "context": ["research_task"]}
              ]
            }
        
        Result:
            write_task.context = [research_task_object]
        """
        task_map: Dict[str, Task] = {}
        tasks: List[Task] = []
        
        logger.info(f"Building {len(task_specs)} tasks (pass 1: creation)")
        
        # PASS 1: Create all Task objects WITHOUT context
        for idx, spec in enumerate(task_specs):
            task = spec.as_crew_task(agents, ctxt=self.context)
            tasks.append(task)
            
            # Ensure task has a name for indexing
            task_name = spec.name or task.name
            if not task_name:
                # Auto-generate name if missing
                task_name = f"{spec.agent}_task_{idx}"
                task.name = task_name
            
            task_map[task_name] = task
            logger.debug(f"Created task: '{task_name}'")
        
        logger.info(f"Resolving task context (pass 2)")
        
        # PASS 2: Resolve context string names → Task object references
        for idx, (spec, task) in enumerate(zip(task_specs, tasks)):
            
            # No context specified → use CrewAI sequential default
            if not spec.context or len(spec.context) == 0:
                if idx == 0:
                    task.context = []  # First task: no context
                else:
                    task.context = [tasks[idx - 1]]  # Auto-chain to previous
                continue
            
            # Resolve context references
            resolved = []
            for ref in spec.context:
                if ref in task_map:
                    resolved.append(task_map[ref])
                    logger.debug(f"Task '{task.name}' → context: '{ref}' ✓")
                else:
                    logger.warning(
                        f"Task '{task.name}' references unknown context '{ref}'. "
                        f"Available: {list(task_map.keys())}"
                    )
            
            task.context = resolved
            if resolved:
                logger.info(
                    f"Task '{task.name}' context: {[t.name for t in resolved]}"
                )
        
        logger.info(f"✓ Built {len(tasks)} tasks")
        return tasks
    
    def build_crew(
        self,
        crew_spec,
        llm,
        job_id: str,
        planning_llm=None,
        embedder=None,
        knowledge_sources=None,
        **kwargs
    ) -> Crew:
        """
        Build complete Crew with agents, tasks, and resolved context.
        
        Args:
            crew_spec: CrewA specification object
            llm: LLM instance for crew
            planning_llm: Optional LLM for planning agent (with JWT auth)
            embedder: Optional embedder configuration for embeddings via LiteLLM proxy
            knowledge_sources: Optional list of knowledge sources (from previous crew outputs)
            job_id: Job identifier
            **kwargs: Additional Crew parameters (memory, verbose, planning, etc.)
        
        Returns:
            CrewAI Crew ready for execution
        
        Example:
            builder = CrewBuilder(context)
            crew = builder.build_crew(
                crew_spec=crew_def,
                llm=llm_instance,
                planning_llm=planning_llm_instance,
                embedder=embedder_config,
                knowledge_sources=[StringKnowledgeSource(...)],
                job_id="urn:ivcap:job:123",
                memory=False,
                verbose=True
            )
            result = crew.kickoff(inputs={"topic": "AI"})
        """
        logger.info(f"Building crew: {crew_spec.name}")
        
        # Step 1: Build agents
        agents = self.build_agents(crew_spec.agents, crew_llm=llm)
        
        # Step 2: Build tasks with context resolution
        tasks = self.build_tasks(crew_spec.tasks, agents)
        
        # Step 3: Determine process type
        process = (
            Process.sequential 
            if crew_spec.process == "sequential" 
            else Process.hierarchical
        )
        
        # Step 4: Construct Crew
        crew_config = {
            "name": crew_spec.name,
            "agents": list(agents.values()),
            "tasks": tasks,
            "llm": llm,
            "planning_llm": planning_llm,
            "process": process,
            "verbose": crew_spec.verbose if isinstance(crew_spec.verbose, bool) else True,
            "planning": crew_spec.planning if crew_spec.planning is not None else False,
            "cache": crew_spec.cache if crew_spec.cache is not None else True,
            "memory": crew_spec.memory if crew_spec.memory is not None else False,
        }
        
        # Add embedder if provided
        if embedder:
            crew_config["embedder"] = embedder
        
        # Add knowledge sources if provided
        if knowledge_sources:
            crew_config["knowledge_sources"] = knowledge_sources
            logger.info(f"✓ Added {len(knowledge_sources)} knowledge source(s) to crew")
        
        # Add optional parameters
        if crew_spec.max_rpm:
            crew_config["max_rpm"] = crew_spec.max_rpm
        
        # Override with kwargs
        crew_config.update(kwargs)
        
        logger.info(
            f"Crew config: {len(agents)} agents, {len(tasks)} tasks, "
            f"process={process.value}"
        )
        
        crew = Crew(**crew_config)
        return crew

