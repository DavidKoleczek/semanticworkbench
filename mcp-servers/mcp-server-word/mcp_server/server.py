from mcp.server.fastmcp import FastMCP


from . import settings

# Set the name of the MCP server
server_name = "Word MCP Server"

def create_mcp_server() -> FastMCP:

    # Initialize FastMCP with debug logging.
    mcp = FastMCP(name=server_name, log_level=settings.log_level)

    # Define each tool and its setup.

    # Example tool
    @mcp.tool()    
    async def echo(value: str) -> str:
        """
        Will return whatever is passed to it.
        """

        return value

    # Add a multiplication tool
    @mcp.tool()
    async def multiply(a: float, b: float) -> float:
        """
        Multiplies two numbers and returns the result.

        Args:
            a: The first number.
            b: The second number.

        Returns:
            The product of the two numbers.
        """
        return a * b

    return mcp
