'''
`python` command heavily influenced by jishaku py command
'''

import asyncio
import collections
import contextlib
import sys

import discord
import humanize as humanise
from discord.ext import commands
from jishaku.codeblocks import codeblock_converter
from jishaku.cog_base import CommandTask
from jishaku.exception_handling import ReplResponseReactor
from jishaku.functools import AsyncSender
from jishaku.paginators import PaginatorInterface
from jishaku.repl import get_var_dict_from_ctx
from jishaku.repl.compilation import AsyncCodeExecutor
from jishaku.repl.scope import Scope
import inspect


from .backend.paginator.paginator import paginator

try:
    import psutil
except ImportError:
    psutil = None

class Dev(commands.Cog):
    '''
    Dev commands
    '''
    def __init__(self, bot):
        self.bot = bot
        self.last_result = None
        self._scope = Scope()
        self.task_count: int = 0
        self.tasks = collections.deque()

    @contextlib.contextmanager
    def submit(self, ctx: commands.Context):
        """
        A context-manager that submits the current task to jishaku's task list
        and removes it afterwards.

        Parameters
        -----------
        ctx: commands.Context
            A Context object used to derive information about this command task.
        """

        self.task_count += 1

        if sys.version_info < (3, 7, 0):
            cmdtask = CommandTask(
                self.task_count, ctx, asyncio.Task.current_task())  # pylint: disable=no-member
        else:
            try:
                current_task = asyncio.current_task()  # pylint: disable=no-member
            except RuntimeError:
                current_task = None

            cmdtask = CommandTask(self.task_count, ctx, current_task)

        self.tasks.append(cmdtask)

        try:
            yield cmdtask
        finally:
            if cmdtask in self.tasks:
                self.tasks.remove(cmdtask)
    
    @commands.is_owner()
    @commands.group(name="dev", invoke_with_command=True)
    async def _dev(self, ctx):
        '''
        The base command for the dev cog, gives system info if not invoked with a subcommand
        '''
        if not ctx.invoked_subcommand:
            embed = discord.Embed(title="System info",
                                  colour=discord.Colour.teal())

            embed.add_field(name=f"Discord.py version",
                            value=f"```\n{discord.__version__}```", inline=True)

            embed.add_field(name=f"Python version",
                            value=f"```\n{sys.version}```", inline=False)

            embed.add_field(name=f"Platform info", value=f"```\n{sys.platform}```".replace('\n', ''), inline=True)

            if psutil:
                try:
                    proc = psutil.Process()

                    with proc.oneshot():
                        mem = proc.memory_full_info()

                        embed.add_field(
                            name=f"Physical memory", value=f"```\n{humanise.naturalsize(mem.rss)}```", inline=True)

                        embed.add_field(
                            name=f"Virtual memory", value=f"```\n{humanise.naturalsize(mem.vms)}```", inline=True)
                        
                        embed.add_field(
                            name=f"Process memory", value=f"```\n{humanise.naturalsize(mem.uss)}```", inline=True)

                        name = proc.name()
                        pid = proc.pid
                        thread_count = proc.num_threads()
                        
                        embed.add_field(name=f"PID", value=f"```\n{pid}```", inline=True)
                        embed.add_field(name=f"Process name", value=f"```\n{name}```", inline=True)
                        embed.add_field(name=f"Thread count", value=f"```\n{thread_count}```", inline=True)
                        
                except psutil.AccessDenied:
                    pass
                
            embed.add_field(name=f"Guilds", value=f"```\n{len(self.bot.guilds)}```", inline=True)
            embed.add_field(name=f"Users", value=f"```\n{len(self.bot.users)}```", inline=True)
            
            embed.add_field(name=f"Message cache", value=f"```\n{self.bot._connection.max_messages}```", inline=True)
            
            embed.add_field(name=f"Latency", value=f"```\n{round(self.bot.latency * 1000, 2)}ms```", inline=True)
            
            await ctx.reply(embed=embed, mention_author=False)
    
    @commands.is_owner()
    @_dev.command(name="python", aliases=["py"])
    async def _dev_python(self, ctx, *, code: codeblock_converter):
        '''
        Evaluate python code
        '''
        arg_dict = get_var_dict_from_ctx(ctx, "")
        arg_dict["_"] = self.last_result
        
        scope = self._scope
        
        try:
            async with ReplResponseReactor(ctx.message):
                with self.submit(ctx):
                    executor = AsyncCodeExecutor(
                        code.content, scope, arg_dict=arg_dict)
                    async for send, result in AsyncSender(executor):
                        if result is None:
                            continue

                        self.last_result = result

                        if isinstance(result, discord.File):
                            send(await ctx.reply(file=result))
                        elif isinstance(result, discord.Embed):
                            send(await ctx.reply(embed=result))
                        elif isinstance(result, PaginatorInterface):
                            send(await result.send_to(ctx))
                        else:
                            if not isinstance(result, str):
                                result = repr(result)

                            if len(result) > 2000:
                                result = result.replace("`", "`\u200b")
                                width = 2000
                                pages = [result[i:i + width] for i in range(0, len(result), width)]
                                
                                for page in pages:
                                    embed = discord.Embed(description=f"```py\n{page}```", colour=discord.Colour.teal())
                                    pages[pages.index(page)] = embed
                                    
                                embedpaginator = paginator(ctx, remove_reactions=True)
                                embedpaginator.add_reaction("\U000023ea", "first")
                                embedpaginator.add_reaction("\U000025c0", "back")
                                embedpaginator.add_reaction("\U0001f5d1", "delete")
                                embedpaginator.add_reaction("\U000025b6", "next")
                                embedpaginator.add_reaction("\U000023e9", "last")
                                send(await embedpaginator.send(pages))
                            
                            else:
                                if result.strip() == '':
                                    result = "\u200b"

                                embed = discord.Embed(description=f"```py\n{result.replace(self.bot.http.token, '[token]')}```", colour=discord.Colour.teal())
                                
                                send(await ctx.reply(embed=embed, mention_author=False))
        finally:
            scope.clear_intersection(arg_dict)
        
    @commands.is_owner()
    @commands.command(name="eval")
    async def _eval(self, ctx, *, code: codeblock_converter):
        '''
        A shortcut for the command `dev python`
        '''
        await self._dev_python(ctx, code=code)

    @commands.is_owner()
    @_dev.command(name="source", aliases=["src"])
    async def _dev_source(self, ctx, *, command_name):
        '''
        Get the source code for the given command
        '''
        command = self.bot.get_command(command_name)
        if not command:
            embed = discord.Embed(title="Error!", description=f"Couldn't find the command `{command_name}`!", colour=discord.Colour.red())
            return await ctx.reply(embed=embed, mention_author=False)
        
        try:
            lines, _ = inspect.getsourcelines(command.callback)
        except (TypeError, OSError):
            embed = discord.Embed(title="Error!", description=f"Couldn't retrieve the source for the command `{command_name}`!", colour=discord.Colour.red())
            return await ctx.reply(embed=embed, mention_author=False)
        
        result = ''.join(lines).replace("`", "`\u200b")
        
        if len(result) > 2000:
            width = 2000
            pages = [result[i:i + width] for i in range(0, len(result), width)]
            
            for page in pages:
                embed = discord.Embed(description=f"```py\n{page}```", colour=discord.Colour.teal())
                pages[pages.index(page)] = embed

            embedpaginator = paginator(ctx, remove_reactions=True)
            embedpaginator.add_reaction("\U000023ea", "first")
            embedpaginator.add_reaction("\U000025c0", "back")
            embedpaginator.add_reaction("\U0001f5d1", "delete")
            embedpaginator.add_reaction("\U000025b6", "next")
            embedpaginator.add_reaction("\U000023e9", "last")
            await embedpaginator.send(pages)
        else:
            embed = discord.Embed(description=f"```py\n{result}```", colour=discord.Colour.teal())
            msg = await ctx.reply(embed=embed, mention_author=False)
            
            def check(reaction, user):
                return user.id == ctx.author.id
            
            await msg.add_reaction("\U000023f9")
            
            try:
                reaction, user = await self.bot.wait_for("reaction_add", check=check, timeout=60)
            except asyncio.TimeoutError:
                pass
            else:
                await msg.delete()
            

    @commands.is_owner()
    @_dev.command(name="purge", aliases=["cleanup"])
    async def _purge(self, ctx, amount=10):
        '''
        Clean up the bot's messages
        '''
        def check(m):
            return m.author == self.bot.user
        
        try:
            await ctx.channel.purge(limit=amount, check=check, bulk=False)
            await ctx.message.add_reaction("\U0001f44c")
        except Exception as e:
            embed = discord.Embed(title="Error!", description=f"```diff\n- {e}", colour=discord.Colour.red())
            await ctx.send(embed=embed)

def setup(bot):
    bot.add_cog(Dev(bot))
