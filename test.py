import asyncio
from firecrawl import FirecrawlApp
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
from dotenv import load_dotenv
import os ,json
load_dotenv()

firecrawl_api_key=os.getenv("FIRECRAWL_API_KEY")
firecrawl = FirecrawlApp(api_key=firecrawl_api_key)

async def search_interview_questions(
    job_description: str
) -> str:
    """
    Firecrawl: Search for relevant interview resources.
    Crawl4AI: Crawl discovered URLs and extract Markdown.
    """

    try:
        # 1. Generate targeted search queries
        jd = job_description[:300]


        search_queries = [
            f"Interview experiences and interview rounds for {jd}",
            f"Technical interview questions and assessments for {jd}",
            f"Practical coding and project interview questions for {jd}",
            f"Behavioral and experience-based interview questions for {jd}",
            
        ]

        all_results = []

        # 2. Search using Firecrawl
        for query in search_queries:

            try:
                response = await asyncio.to_thread(firecrawl.search, query, limit=5)

                results = (
                    response.get("web", [])
                    if isinstance(response, dict)
                    else getattr(response, "web", [])
                )

                all_results.extend(results)

            except Exception as e:
                print(f"Search failed: {e}")

        # 3. Deduplicate URLs
        unique_urls = {}

        for result in all_results:

            url = (
                result.get("url")
                if isinstance(result, dict)
                else getattr(result, "url", None)
            )

            if url:
                unique_urls[url] = result

        urls = list(unique_urls.keys())[:20]

        if not urls:
            return "No result found"
        # 4. Crawl discovered URLs using Crawl4AI
        all_crawled_pages = []

        config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
            word_count_threshold=100,
            remove_overlay_elements=True
        )

        async with AsyncWebCrawler() as crawler:

            crawl_results = await crawler.arun_many(
                urls=urls,
                config=config
            )

            for result in crawl_results:

                if not result.success:
                    continue

                markdown = result.markdown
                print(markdown)

                # Support different Markdown result formats
                if hasattr(markdown, "raw_markdown"):
                    content = markdown.raw_markdown
                else:
                    content = str(markdown)

                if not content or not content.strip():
                    continue

                all_crawled_pages.append({
                    "source_url": result.url,
                    "title": getattr(
                        result,
                        "metadata",
                        {}
                    ).get("title", ""),
                    "content": content
                })

        # 5. Return extracted research
        return json.dumps({
            "success": True,
            "total_search_results": len(unique_urls),
            "results": all_crawled_pages,
                    }, ensure_ascii=False)

    except Exception as e:

        return json.dumps({
            "success": False,
            "error": str(e)
        })

job_description="""
We are looking for curious, analytical, and technically strong students who want to apply Data Science
and AI to real-world problems.
As a Data Science Intern, you will work on practical projects involving Machine Learning, Generative AI,
LLMs, predictive modelling, data analytics, and intelligent automation. You will contribute to solutions
that move beyond experimentation and are designed to solve actual business problems.
This role is ideal for candidates who enjoy understanding how things work, experimenting with new
approaches, writing clean code, and turning ideas into working solutions.
K E Y R E S P O N S I B I L I T I E S
• Machine Learning & Predictive Modelling: Explore datasets, engineer features, train models,
evaluate performance, and develop solutions for prediction, classification, risk assessment, and
forecasting.
• Generative AI & LLMs: Work with large language models, prompt engineering, structured outputs,
tool calling, and LLM-powered applications.
• AI Application Development: Contribute to AI-powered workflows, intelligent automation,
document processing, recommendation systems, and other practical applications.
• Data Analysis & Preparation: Clean, transform, validate, and analyse datasets to identify patterns,
generate insights, and prepare data for modelling.
• Python Development & APIs: Build reusable Python components and integrate models or AI
capabilities into applications using APIs and frameworks such as FastAPI.
• Experimentation & Evaluation: Compare approaches, select appropriate evaluation metrics, analyse
failures, and improve model performance and reliability.
• Production-Oriented Problem Solving: Understand how models and AI systems can be deployed,
monitored, optimized, and integrated into existing business workflows.
• Business Collaboration: Work with the Data Science and other technology teams to understand
business requirements and translate them into practical technical solutions.
R E Q U I R E D S K I L L S & Q U A L I F I C A T I O N S
• Strong fundamentals in Python programming, data structures, and object-oriented programming.

Kaabil Finance Pvt. Ltd. | Jaipur, Rajasthan | Page 2

• Good understanding of Machine Learning concepts, including supervised and unsupervised learning,
regression, classification, model evaluation, and feature engineering.
• Solid understanding of statistics, probability, and analytical problem-solving.
• Hands-on familiarity with Pandas, NumPy, and Scikit-learn.
• Understanding of data preprocessing, exploratory data analysis, and model evaluation techniques.
• Familiarity with Generative AI and LLM fundamentals, including prompting, tokens, context windows,
and common use cases.
• Ability to break down complex problems, reason logically, and develop practical solutions.
• Genuine curiosity to explore unfamiliar technologies, learn independently, and improve existing
approaches.
G O O D T O H A V E
• Hands-on experience building projects using LLM APIs, such as Gemini or other comparable models.
• Understanding of RAG, embeddings, vector search, agentic workflows, or AI tool calling.
• Familiarity with FastAPI, REST APIs, MongoDB, and Git.
• Exposure to recommendation systems, NLP, computer vision.
• Experience deploying models or integrating AI capabilities into applications.
These are additional advantages, not substitutes for strong Python, analytical, and Machine Learning
fundamentals.
W H A T W E L O O K F O R
We value candidates who:
• Understand the reasoning behind an algorithm or model rather than simply knowing how to use a
library.
• Can explain their projects clearly, including design decisions, limitations, and results.
• Approach unfamiliar problems with structured thinking and a willingness to experiment.
• Care about code quality, data accuracy, efficiency, and reliable implementation.
• Take ownership of their work and proactively identify opportunities to improve a solution.
• Are interested in building AI systems that deliver measurable business value.
W H A T Y O U W I L L G A I N
• Hands-on experience working on real-world AI/ML and GenAI applications in the financial-services
domain.
• Exposure to practical use cases involving predictive modelling, risk analytics, intelligent automation,
and AI-powered workflows.
• Experience working with real engineering constraints, including data quality, performance, reliability,
and integration.
• Opportunities to learn from experienced technology and Data Science professionals.
• Exposure to the complete problem-solving lifecycle — from understanding a business problem and
preparing data to developing, evaluating, and integrating a solution.
• Potential Pre-Placement Offer (PPO) based on internship performance, technical capability,
ownership, and business impact.

Kaabil Finance Pvt. Ltd. | Jaipur, Rajasthan | Page 3

O U R E X P E C T A T I O N S
We are not looking for candidates who only know how to run existing notebooks or call an AI API. We
want people who can understand a problem, reason through possible solutions, build working
implementations, evaluate results, and continuously improve their work.
If you enjoy Python, understand Machine Learning, and want to build practical AI solutions that go
beyond demos, we would love to meet you.
C O M P E N S A T I O N
Employment type Internship
Duration 6 Months
Fixed stipend ₹25,000 per month
Pre-Placement Offer (PPO) If selected, based on performance
PPO package ₹10 Lakhs total (₹7 Lakhs CTC + ₹3 Lakhs ESOP)
"""
response=asyncio.run(search_interview_questions(job_description))
print(response)