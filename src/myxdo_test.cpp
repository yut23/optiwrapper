extern "C" {
#include "myxdo.h"
}
#include <algorithm> // for set_difference
#include <cstdlib>   // for free
#include <iostream>  // for operator<<, endl, cout
#include <iterator>  // for back_inserter
#include <set>       // for operator!=, set
#include <vector>    // for vector

int main() {
  xdo_t *xdo = xdo_new(nullptr);
  Window *windowlist = nullptr;
  unsigned int nwindows;
  xdo_search_t search{
      .winclassname = "^osu!.exe$",
      .winname = "^osu!$",
      .max_depth = -1,
      .only_visible = 1,
      .require = xdo_search::SEARCH_ALL,
      .searchmask = SEARCH_NAME | SEARCH_CLASSNAME,
  };
  std::set<Window> curr_windows{};
  std::set<Window> prev_windows{};
  std::vector<Window> temp{};
  std::cout << std::hex;

  while (true) {
    xdo_search_windows(xdo, &search, &windowlist, &nwindows);
    curr_windows = std::set<Window>{windowlist, windowlist + nwindows};
    std::free(windowlist);

    std::set_difference(curr_windows.begin(), curr_windows.end(),
                        prev_windows.begin(), prev_windows.end(),
                        std::back_inserter(temp));
    for (auto i : temp) {
      std::cout << "opened: 0x" << i << std::endl;
    }
    temp.clear();

    std::set_difference(prev_windows.begin(), prev_windows.end(),
                        curr_windows.begin(), curr_windows.end(),
                        std::back_inserter(temp));
    for (auto i : temp) {
      std::cout << "closed: 0x" << i << std::endl;
    }
    temp.clear();
    prev_windows = curr_windows;
  }

  xdo_free(xdo);
  return 0;
}
