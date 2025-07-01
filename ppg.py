#a little wrapper to create a shorthand alias
import sys

from protocol_gateway import main

if __name__ == "__main__":
    # Pass sys.argv (or the relevant slice) to main()
    # assuming your main accepts them as parameters
    main(sys.argv[1:]) # pass all args except script name